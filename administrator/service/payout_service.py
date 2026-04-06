# administrator/service/payout_service.py

"""
Secure Paystack Payout Service

Fixes applied:
1. Recipient code cached on PayoutInformation — never created twice
2. Account number verified via Paystack resolve API before first recipient creation
3. Idempotent references — safe to retry without double-crediting
4. Bulk transfer API used for multiple payouts in one call
5. Bank code stored directly on PayoutInformation (no fragile dict mapping)
6. Transfer code and status saved back to Withdrawal metadata
7. @transaction.atomic removed from functions that call external APIs
   (atomic + external HTTP = dangerous — DB rolls back but money already sent)
8. Celery task wrapper for async processing
9. Minimum amount check before initiating transfer
10. OTP-disabled assumed (if OTP is enabled on account, transfers need separate OTP confirm)
"""

import logging
import uuid
import requests
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

PAYSTACK_API_BASE = "https://api.paystack.co"
MINIMUM_PAYOUT_AMOUNT = Decimal("100.00")  # minimum ₦100


def _paystack_headers():
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type":  "application/json",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API — called from views
# ─────────────────────────────────────────────────────────────────────────────

class AdminPayoutActionService:

    @staticmethod
    def bulk_approve(withdrawal_ids, admin_user):
        """
        Validates, marks as approved in DB, then fires Celery task for transfers.
        Returns (succeeded_ids, failed_list).

        IMPORTANT: We do NOT wrap this in @transaction.atomic because
        the external Paystack call must not be rolled back if DB fails.
        Each withdrawal is handled independently.
        """
        from transactions.models import Withdrawal

        withdrawals = list(
            Withdrawal.objects
            .filter(id__in=withdrawal_ids, status="pending")
            .select_related("user", "payout_account")
        )

        if not withdrawals:
            return [], [{"id": str(wid), "reason": "Not found or not pending"} for wid in withdrawal_ids]

        succeeded = []
        failed    = []

        for withdrawal in withdrawals:
            # Minimum amount check
            if withdrawal.amount < MINIMUM_PAYOUT_AMOUNT:
                failed.append({
                    "id":     str(withdrawal.id),
                    "reason": f"Amount ₦{withdrawal.amount} is below minimum ₦{MINIMUM_PAYOUT_AMOUNT}",
                })
                continue

            try:
                # 1 — Mark approved in DB first (safe — no external call yet)
                with transaction.atomic():
                    Withdrawal.objects.filter(id=withdrawal.id).update(status="approved")

                # 2 — Queue Celery task for actual transfer (non-blocking)
                from administrator.tasks import process_single_payout
                process_single_payout.delay(str(withdrawal.id), admin_user.email)

                succeeded.append(str(withdrawal.id))
                logger.info(f"Withdrawal {withdrawal.id} approved, payout task queued")

            except Exception as e:
                logger.error(f"Failed to approve withdrawal {withdrawal.id}: {e}")
                failed.append({"id": str(withdrawal.id), "reason": str(e)})

        return succeeded, failed

    @staticmethod
    def bulk_decline(withdrawal_ids, admin_user, reason=""):
        """Marks withdrawals as rejected. Pure DB operation — safe to be atomic."""
        from transactions.models import Withdrawal

        succeeded = []
        failed    = []

        for wid in withdrawal_ids:
            try:
                with transaction.atomic():
                    updated = Withdrawal.objects.filter(
                        id=wid, status="pending"
                    ).update(status="rejected")

                    if updated == 0:
                        failed.append({"id": str(wid), "reason": "Not found or not pending"})
                        continue

                succeeded.append(str(wid))
                logger.info(
                    f"Admin {admin_user.email} declined withdrawal {wid}. "
                    f"Reason: {reason or 'none'}"
                )
            except Exception as e:
                logger.error(f"Failed to decline withdrawal {wid}: {e}")
                failed.append({"id": str(wid), "reason": str(e)})

        return succeeded, failed


# ─────────────────────────────────────────────────────────────────────────────
# Internal Paystack Transfer Logic — called from Celery task
# ─────────────────────────────────────────────────────────────────────────────

class PaystackPayoutService:

    @staticmethod
    def process_withdrawal(withdrawal_id):
        """
        Called from Celery. Handles the full transfer flow for one withdrawal:
          1. Ensure payout account has a verified recipient_code
          2. Initiate transfer with idempotent reference
          3. Save transfer_code and status back to withdrawal metadata
        """
        from transactions.models import Withdrawal

        try:
            withdrawal = Withdrawal.objects.select_related(
                "user", "payout_account"
            ).get(id=withdrawal_id)
        except Withdrawal.DoesNotExist:
            logger.error(f"process_withdrawal: Withdrawal {withdrawal_id} not found")
            return

        if withdrawal.status != "approved":
            logger.warning(f"process_withdrawal: Withdrawal {withdrawal_id} is not approved, skipping")
            return

        payout = withdrawal.payout_account

        # Step 1 — Ensure recipient code exists (create if not)
        try:
            recipient_code = PaystackPayoutService._ensure_recipient_code(payout)
        except PaystackPayoutError as e:
            PaystackPayoutService._mark_failed(withdrawal, f"Recipient creation failed: {e}")
            return

        # Step 2 — Initiate transfer with idempotent reference
        # Reference is always based on withdrawal.id — safe to retry
        reference = f"qavtix_payout_{withdrawal.id}"

        try:
            transfer_data = PaystackPayoutService._initiate_transfer(
                recipient_code = recipient_code,
                amount_kobo    = int(float(withdrawal.amount) * 100),
                reference      = reference,
                withdrawal_id  = withdrawal.id,
            )
        except PaystackPayoutError as e:
            PaystackPayoutService._mark_failed(withdrawal, f"Transfer failed: {e}")
            return

        # Step 3 — Save transfer details to metadata
        # Status is now "pending" on Paystack side — webhook will confirm "success"/"failed"
        metadata = withdrawal.metadata or {}
        metadata.update({
            "transfer_code":    transfer_data.get("transfer_code"),
            "paystack_status":  transfer_data.get("status"),
            "paystack_ref":     reference,
            "transfer_initiated_at": timezone.now().isoformat(),
        })

        # Mark as "paid" optimistically — webhook can correct if it fails
        withdrawal.status   = "paid"
        withdrawal.metadata = metadata
        withdrawal.save(update_fields=["status", "metadata"])

        logger.info(
            f"Transfer initiated for withdrawal {withdrawal.id}: "
            f"code={transfer_data.get('transfer_code')}, "
            f"status={transfer_data.get('status')}"
        )

    @staticmethod
    def process_bulk_withdrawals(withdrawal_ids):
        """
        Processes multiple withdrawals in one Paystack bulk transfer call.
        More efficient than individual calls for large batches.
        """
        from transactions.models import Withdrawal

        withdrawals = list(
            Withdrawal.objects
            .filter(id__in=withdrawal_ids, status="approved")
            .select_related("user", "payout_account")
        )

        if not withdrawals:
            return

        transfers = []
        valid_withdrawals = []

        for withdrawal in withdrawals:
            payout = withdrawal.payout_account
            try:
                recipient_code = PaystackPayoutService._ensure_recipient_code(payout)
            except PaystackPayoutError as e:
                PaystackPayoutService._mark_failed(withdrawal, f"Recipient error: {e}")
                continue

            transfers.append({
                "amount":    int(float(withdrawal.amount) * 100),
                "recipient": recipient_code,
                "reference": f"qavtix_payout_{withdrawal.id}",
                "reason":    f"QavTix payout #{withdrawal.id}",
            })
            valid_withdrawals.append(withdrawal)

        if not transfers:
            return

        # Paystack bulk transfer — one API call for all
        try:
            response = requests.post(
                f"{PAYSTACK_API_BASE}/transfer/bulk",
                headers=_paystack_headers(),
                json={"currency": "NGN", "source": "balance", "transfers": transfers},
                timeout=60,
            )
            response.raise_for_status()
            results = response.json().get("data", [])

            for i, withdrawal in enumerate(valid_withdrawals):
                result = results[i] if i < len(results) else {}
                metadata = withdrawal.metadata or {}
                metadata.update({
                    "transfer_code":   result.get("transfer_code"),
                    "paystack_status": result.get("status"),
                    "paystack_ref":    f"qavtix_payout_{withdrawal.id}",
                    "bulk_transfer":   True,
                })
                withdrawal.status   = "paid"
                withdrawal.metadata = metadata
                withdrawal.save(update_fields=["status", "metadata"])

        except requests.RequestException as e:
            logger.error(f"Bulk transfer failed: {e}")
            for withdrawal in valid_withdrawals:
                PaystackPayoutService._mark_failed(withdrawal, f"Bulk transfer error: {e}")

    @staticmethod
    def _ensure_recipient_code(payout_account):
        """
        Returns existing recipient_code from payout_account if cached.
        Otherwise verifies account number with Paystack, creates recipient,
        saves recipient_code to the DB for reuse forever.
        """
        if payout_account.recipient_code:
            return payout_account.recipient_code

        if not payout_account.bank_code:
            raise PaystackPayoutError(
                f"No bank_code on payout account {payout_account.id}. "
                f"Host must re-save their bank details."
            )

        # Step 1 — Verify account number (compliance + correctness)
        PaystackPayoutService._verify_account_number(
            account_number = payout_account.account_number,
            bank_code      = payout_account.bank_code,
        )

        # Step 2 — Create recipient on Paystack
        response = requests.post(
            f"{PAYSTACK_API_BASE}/transferrecipient",
            headers=_paystack_headers(),
            json={
                "type":           "nuban",
                "name":           payout_account.account_name,
                "account_number": payout_account.account_number,
                "bank_code":      payout_account.bank_code,
                "currency":       "NGN",
            },
            timeout=30,
        )

        if not response.ok:
            raise PaystackPayoutError(
                f"Failed to create Paystack recipient: {response.text}"
            )

        data           = response.json().get("data", {})
        recipient_code = data.get("recipient_code")

        if not recipient_code:
            raise PaystackPayoutError("Paystack returned no recipient_code")

        # Step 3 — Cache recipient_code permanently
        type(payout_account).objects.filter(id=payout_account.id).update(
            recipient_code=recipient_code
        )
        payout_account.recipient_code = recipient_code

        logger.info(
            f"Paystack recipient created and cached for payout account "
            f"{payout_account.id}: {recipient_code}"
        )
        return recipient_code

    @staticmethod
    def _verify_account_number(account_number, bank_code):
        """
        Calls Paystack's resolve API to confirm account number + bank_code
        match a real account. Raises PaystackPayoutError if mismatch.
        """
        response = requests.get(
            f"{PAYSTACK_API_BASE}/bank/resolve",
            headers=_paystack_headers(),
            params={
                "account_number": account_number,
                "bank_code":      bank_code,
            },
            timeout=30,
        )

        if not response.ok:
            raise PaystackPayoutError(
                f"Account verification failed for {account_number}: {response.text}"
            )

        data = response.json().get("data", {})
        logger.info(
            f"Account verified: {account_number} → {data.get('account_name')} "
            f"at bank {bank_code}"
        )

    @staticmethod
    def _initiate_transfer(recipient_code, amount_kobo, reference, withdrawal_id):
        """
        Initiates a Paystack transfer. Uses the same reference on retry
        so Paystack deduplicates and never double-credits.
        """
        response = requests.post(
            f"{PAYSTACK_API_BASE}/transfer",
            headers=_paystack_headers(),
            json={
                "source":    "balance",
                "amount":    amount_kobo,
                "recipient": recipient_code,
                "reason":    f"QavTix payout #{withdrawal_id}",
                "reference": reference,  # idempotent — Paystack deduplicates by this
            },
            timeout=30,
        )

        if not response.ok:
            raise PaystackPayoutError(
                f"Paystack transfer failed: {response.text}"
            )

        return response.json().get("data", {})

    @staticmethod
    def _mark_failed(withdrawal, reason):
        """Saves failure reason to metadata. Does not change status from 'approved'."""
        metadata = withdrawal.metadata or {}
        metadata["transfer_failure"] = reason
        metadata["transfer_failed_at"] = timezone.now().isoformat()
        withdrawal.metadata = metadata
        withdrawal.save(update_fields=["metadata"])
        logger.error(f"Withdrawal {withdrawal.id} transfer failed: {reason}")


class PaystackPayoutError(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Paystack Transfer Webhook Handler
# ─────────────────────────────────────────────────────────────────────────────

class PaystackTransferWebhookService:
    """
    Handles transfer.success and transfer.failed webhook events from Paystack.
    Wire this into your existing webhook view.

    In your PaystackWebhookService.handle():
        elif event_type == "transfer.success":
            return PaystackTransferWebhookService.handle_success(data)
        elif event_type == "transfer.failed":
            return PaystackTransferWebhookService.handle_failed(data)
    """

    @staticmethod
    def handle_success(data):
        reference = data.get("reference", "")
        PaystackTransferWebhookService._update_withdrawal(reference, "paid", data)
        return {"handled": True, "flow": "transfer_success", "reference": reference}

    @staticmethod
    def handle_failed(data):
        reference = data.get("reference", "")
        PaystackTransferWebhookService._update_withdrawal(reference, "approved", data)
        logger.warning(f"Paystack transfer FAILED for reference {reference}")
        return {"handled": True, "flow": "transfer_failed", "reference": reference}

    @staticmethod
    def _update_withdrawal(reference, new_status, data):
        from transactions.models import Withdrawal

        try:
            withdrawal = Withdrawal.objects.get(
                metadata__paystack_ref=reference
            )
        except Withdrawal.DoesNotExist:
            logger.warning(f"Transfer webhook: no withdrawal found for ref {reference}")
            return

        metadata = withdrawal.metadata or {}
        metadata["webhook_status"] = data.get("status")
        metadata["webhook_at"]     = timezone.now().isoformat()

        withdrawal.status   = new_status
        withdrawal.metadata = metadata
        withdrawal.save(update_fields=["status", "metadata"])
        logger.info(f"Withdrawal {withdrawal.id} updated to '{new_status}' via webhook")