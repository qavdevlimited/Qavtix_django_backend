from abc import ABC, abstractmethod

class PaymentGateway(ABC):

    @abstractmethod
    def create_customer(self, user):
        pass

    @abstractmethod
    def add_card(self, user, payment_method_id):
        pass

    @abstractmethod
    def charge_card(self, user, card, amount, currency="USD"):
        pass