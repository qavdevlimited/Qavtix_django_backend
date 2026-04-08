"""
email_templates.py
──────────────────
QavTix HTML email template builder.

Usage
-----
from email_templates import build_email

html = build_email(
    title="Important Update",
    body_html="<p>Hello, World!</p>",
    logo_path="/path/to/logo.png",   # absolute path on disk → embedded as base64
)
"""

import base64
import mimetypes
import os


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _embed_image(path: str) -> str:
    """Return a data-URI string for the image at *path*."""
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "image/png"
    with open(path, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode()
    return f"data:{mime};base64,{encoded}"


# ─────────────────────────────────────────────────────────────────────────────
# Core template
# ─────────────────────────────────────────────────────────────────────────────

def build_email(
    title: str,
    body_html: str,
    logo_path: str | None = None,
    logo_alt: str = "QavTix",
) -> str:
    """
    Dark, seamless professional email template (no inner box).
    """
    import os

    # Logo handling
    if logo_path and os.path.isfile(logo_path):
        logo_html = (
            f'<img src="{_embed_image(logo_path)}" '
            f'alt="{logo_alt}" '
            f'style="height:42px; width:auto; max-width:190px; display:block; margin:0 auto;" />'
        )
    else:
        logo_html = (
            f'<span style="color:#ffffff; font-family:Georgia, serif; '
            f'font-size:26px; font-weight:bold; letter-spacing:0.5px;">'
            f'{logo_alt}</span>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
</head>

<body style="margin:0; padding:0; background-color:#1a2035; font-family:Arial, Helvetica, sans-serif;">

  <!-- Full background -->
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background-color:#1a2035; min-width:100%;">
    <tr>
      <td style="padding:0;">

        <!-- Main dark container -->
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="max-width:720px; width:100%; background-color:#1e2540; border-radius:8px; overflow:hidden; margin:0 auto;">

          <!-- Header -->
          <tr>
            <td style="background-color:#b8d4f0; padding:22px 28px; text-align:center;">
              <p style="margin:0; color:#1a2035; font-size:18px; font-weight:700; line-height:1.4;">
                {title}
              </p>
            </td>
          </tr>

          <!-- Body (NO inner box anymore) -->
          <tr>
            <td style="padding:28px 30px; color:#e6e9f2; font-size:15.5px; line-height:1.78;">
              {body_html}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color:#141929; padding:24px 28px; text-align:center;">
              {logo_html}
              <p style="margin:14px 0 0 0; color:#8a8f9e; font-size:13px;">
                QavTix — Ticketing & Event Support
              </p>
            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>

</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Reusable body builders (one per scenario)
# ─────────────────────────────────────────────────────────────────────────────

def body_incomplete_booking(booking_date: str, order_id: str) -> str:
    return f"""
<p>Hello,</p>
<p>We noticed that you started booking a ticket on <strong>{booking_date}</strong> 
   but didn&apos;t complete the process.</p>
<p><strong>Order ID:</strong> {order_id}</p>
<p>Your selected ticket(s) may still be available, and you can easily pick up 
   where you left off. Simply return to the platform to finish your booking and 
   secure your spot.</p>
<p>Experiencing any issues? reach out to our support team at 
   support@qavtix.com for assistance. Don&apos;t miss out on the event!</p>
<p>Best regards,<br/><strong>The QavTix Team</strong></p>
"""


def body_welcome(first_name: str) -> str:
    return f"""
<p>Hi {first_name},</p>
<p>Welcome to Qavtix! 🎉</p>
<p>We&apos;re excited to have you join our community.</p>
<p>With Qavtix, you can easily discover events, purchase tickets, and manage your 
   event experience all in one place. Whether you're looking for concerts, sports 
   events, conferences, or travel experiences, everything you need is right at 
   your fingertips.</p>
<p>Here&apos;s what you can do next:</p>
<ul style="padding-left:20px;margin:8px 0;">
  <li>Explore upcoming events tailored to your interests</li>
  <li>Purchase and manage tickets securely and effortlessly</li>
  <li>Share tickets with friends or participate in group bookings</li>
  <li>Stay updated with event details and notifications</li>
</ul>
<p>Your account is now ready, and you&apos;re all set to start exploring.</p>
<p>If you have any questions, reach out to us directly at 
   support@qavtix.com. Our support team is always happy to help.</p>
<p>Welcome once again, and enjoy a seamless event experience with Qavtix.</p>
<p>Best regards,<br/><strong>The QavTix Team</strong></p>
"""


def body_otp(otp: str) -> str:
    return f"""
<p>Your verification code (OTP)</p>
<p>Use this to complete your verification</p>
<p>Please use the code below to verify your identity. This OTP is valid for 
   5 minutes. Do not share it with anyone.</p>
<p style="text-align:center;margin:28px 0;">
  <span style="display:inline-block;background:#1a2035;color:#b8d4f0;
               font-size:34px;font-weight:700;letter-spacing:10px;
               padding:16px 28px;border-radius:6px;">
    {otp}
  </span>
</p>
<p>If you did not request this OTP, please ignore this email or contact our 
   support team immediately.</p>
<hr style="border:none;border-top:1px solid #ccc;margin:20px 0;"/>
<p style="font-size:12px;color:#888;text-align:center;">
  This message was sent automatically. Do not reply.<br/>
  &copy; 2025 QavTix. All rights reserved.
</p>
"""


def body_password_changed(first_name: str) -> str:
    return f"""
<p>Hi {first_name},</p>
<p>This is to confirm that your Password has been successfully updated.</p>
<p>You can now log in with your new password and continue accessing your account 
   without interruption.</p>
<p>If you did not make this change, we recommend that you contact us immediately at 
   support@qavtix.com so we can assist in securing your account.</p>
<p>Your security is important to us. Thank you for being part of QavTix.</p>
<p>Best regards,<br/><strong>The QavTix Team</strong></p>
"""


def body_booking_confirmed(
    first_name, order_id, event_name, start_time, start_date,
    end_time, end_date, venue, ticket_type, quantity,
    host_name, host_email, recipient_email
) -> str:
    return f"""
<p>Hi {first_name},</p>
<p>🎉 Your booking is confirmed!</p>
<p>Thank you for choosing QavTix. Your ticket purchase has been successfully 
   completed, and you&apos;re all set for an amazing experience.</p>

<p><strong>🧾 Booking Details</strong></p>
<table role="presentation" width="100%" cellpadding="6" cellspacing="0" 
       style="border-collapse:collapse;margin:16px 0;font-size:14px;">
  <tr style="border-bottom:1px solid #dde;">
    <td style="color:#555;width:40%;">Order ID</td>
    <td><strong>{order_id}</strong></td>
  </tr>
  <tr style="border-bottom:1px solid #dde;">
    <td style="color:#555;">Event</td>
    <td><strong>{event_name}</strong></td>
  </tr>
  <tr style="border-bottom:1px solid #dde;">
    <td style="color:#555;">Date</td>
    <td>From {start_time} {start_date} to {end_time} {end_date} (WAT)</td>
  </tr>
  <tr style="border-bottom:1px solid #dde;">
    <td style="color:#555;">Venue</td>
    <td>{venue}</td>
  </tr>
  <tr style="border-bottom:1px solid #dde;">
    <td style="color:#555;">Ticket Type</td>
    <td>{ticket_type}</td>
  </tr>
  <tr>
    <td style="color:#555;">Quantity</td>
    <td>{quantity}</td>
  </tr>
</table>

<p>Your ticket(s) are attached to this email and are also available in your 
   QavTix account. Please present your QR code at the venue for seamless check-in.</p>

<p><strong>📌 What to Do Next</strong></p>
<ul style="padding-left:20px;margin:8px 0;">
  <li>Save your ticket or download it for easy access</li>
  <li>Arrive early to avoid delays</li>
  <li>Stay updated for any event notifications</li>
</ul>

<p>If you have any questions, feel free to contact the event host 
   <strong>{host_name}</strong> via 
   <a href="mailto:{host_email}" style="color:#3a7bd5;">{host_email}</a>.</p>

<p>Enjoy the event! 🎉</p>
<p>Best regards,<br/><strong>The QavTix Team</strong></p>

<hr style="border:none;border-top:1px solid #ccc;margin:20px 0;"/>
<p style="font-size:11px;color:#888;">
  This email was sent to {recipient_email}. This order is subject to QavTix 
  Terms of Use and Privacy Policy.<br/>
  Create your own event on Qavtix.com and start selling in minutes. Try it today!
</p>
"""


def body_plan_subscribed(
    plan_name: str, order_number: str, duration_label: str, 
    amount: str, renewal_date: str, last4: str = "", card_brand: str = "Visa"
) -> str:
    return f"""
<p>Thank you</p>
<p>You&apos;re subscribed to QavTix {plan_name}, giving you access to premium 
   productivity features across our platform helping you reach a wider audience 
   and boost ticket sales.</p>

<p>Visit the subscription management page to manage your plan. You can also view 
   subscription and payment details at payment.qavtix.com. For questions about 
   the plan and its features visit the Help Center.</p>

<p>QavTix Limited Terms of Service and Refund Policy are applicable to this purchase. 
   Note that QavTix Private Policy describes how data is handled in this service. 
   You can cancel your subscription at any time. Learn more</p>

<table role="presentation" width="100%" cellpadding="6" cellspacing="0" 
       style="border-collapse:collapse;margin:16px 0;font-size:14px;">
  <tr>
    <td style="padding:8px 0;">ITEM</td>
    <td style="padding:8px 0;text-align:center;">QUANTITY</td>
    <td style="padding:8px 0;text-align:right;">PRICE</td>
  </tr>
  <tr>
    <td style="padding:8px 0;">QAVTIX LIMITED</td>
    <td style="padding:8px 0;text-align:center;">1</td>
    <td style="padding:8px 0;text-align:right;">${amount}</td>
  </tr>
</table>

<p>Includes VAT(7.5%) ${round(float(amount)*0.075, 2):.2f}</p>
<p><strong>Total ${amount}</strong></p>
<p>Payment method: {card_brand} ****{last4}</p>
<p>Order number: {order_number}</p>

<p>You will be automatically charged the subscription cost (currently ${amount} every {duration_label}) 
   until you cancel your subscription. Auto-renews on {renewal_date}.</p>

<p>Enjoy your Event,<br/><strong>The QavTix Team</strong></p>
"""


def body_verification_badge(host_name: str) -> str:
    return f"""
<p>Hello {host_name},</p>
<p>🎉 Congratulations! Your QavTix account has been awarded a permanent Blue Verification Badge.</p>
<p>This recognition is given to hosts who consistently meet our platform guidelines 
   through their activity, reliability, and engagement. Your commitment to creating 
   quality events and maintaining trust within the QavTix community has not gone unnoticed.</p>

<p><strong>What This Means for You</strong></p>
<ul style="padding-left:20px;margin:8px 0;">
  <li>A permanent Blue badge displayed on your profile</li>
  <li>Increased trust and credibility with attendees</li>
  <li>Stronger visibility across the QavTix platform</li>
</ul>

<p><strong>Why You Received This Badge</strong></p>
<ul style="padding-left:20px;margin:8px 0;">
  <li>Consistent event activity</li>
  <li>Positive engagement with attendees</li>
  <li>Adherence to QavTix policies and standards</li>
</ul>

<p>This badge is yours to keep as a mark of trust and excellence on QavTix. 
   Keep hosting, growing, and delivering great experiences, we&apos;re proud 
   to have you on the platform.</p>

<p>If you have any questions, feel free to reach out to our support team at 
   support@qavtix.com.</p>

<p>Congratulations once again,<br/><strong>The QavTix Team</strong></p>
"""


def body_plan_renewed(full_name: str, plan_name: str, expires_at: str) -> str:
    return f"""
<p>Hi {full_name},</p>
<p>Great news — your <strong>{plan_name}</strong> plan has been renewed successfully. 🎉</p>
<p><strong>Next expiry date:</strong> {expires_at}</p>
<p>You continue to have full access to all {plan_name} features.</p>
<p>Best regards,<br/><strong>The QavTix Team</strong></p>
"""


def body_plan_renewal_failed(full_name: str, plan_name: str, reason: str) -> str:
    return f"""
<p>Hi {full_name},</p>
<p>Unfortunately, we were unable to automatically renew your <strong>{plan_name}</strong> plan.</p>
<p><strong>Reason:</strong> {reason}</p>
<p>To keep enjoying uninterrupted access, please update your payment method or 
   renew manually.</p>
<p>If you need help, contact us at support@qavtix.com.</p>
<p>Best regards,<br/><strong>The QavTix Team</strong></p>
"""


def body_password_reset_otp(otp: str) -> str:
    return f"""
<p>You requested a password reset for your QavTix account.</p>
<p>Use the code below to reset your password. This code expires in 
   <strong>3 minutes</strong>. Do not share it with anyone.</p>
<p style="text-align:center;margin:28px 0;">
  <span style="display:inline-block;background:#1a2035;color:#b8d4f0;
               font-size:34px;font-weight:700;letter-spacing:10px;
               padding:16px 28px;border-radius:6px;">
    {otp}
  </span>
</p>
<p>If you did not request a password reset, you can safely ignore this email.
   Your account remains secure.</p>
<hr style="border:none;border-top:1px solid #ccc;margin:20px 0;"/>
<p style="font-size:12px;color:#888;text-align:center;">
  This message was sent automatically. Do not reply.<br/>
  &copy; 2025 QavTix. All rights reserved.
</p>
"""