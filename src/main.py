import os
import stripe
import uuid
from dotenv import load_dotenv
from dataclasses import dataclass, field
from stripe import Charge
from stripe.error import StripeError
from pydantic import BaseModel
from typing import Optional, Protocol

_ = load_dotenv()

class ContactInfo(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None

class CustomerData(BaseModel):
    name: str
    contact_info: ContactInfo
    customer_id: Optional[str] = None

class PaymentData (BaseModel):
    amount: int
    source: str

class PaymentResponse(BaseModel):
    status: str
    amount: int
    transaction_id: Optional[str] = None
    message: Optional[str]= None

@dataclass
class CustomerValidator:
    def validate(self, customer_data: CustomerData):
        if not customer_data.name:
            print("Invalid customer data: missing name")
            raise ValueError("Invalid customer data: missing name")
        if not customer_data.contact_info:
            print("Invalid customer data: missing contact info")
            raise ValueError("Invalid customer data: missing contact info")
        if not (
            customer_data.contact_info.email
            or customer_data.contact_info.phone
        ):
            print("Invalid customer data: missing email and phone")
            raise ValueError("Invalid customer data: missing email and phone")

@dataclass
class PaymentValidator:
    def validate(self, payment_data: PaymentData):
        if not payment_data.source:
            print("Invalid payment data: missing source")
            raise ValueError("Invalid payment data: missing source")
        if payment_data.amount <= 0:
            print("Invalid payment data: amount must be positive")
            raise ValueError("Invalid payment data: amount must be positive")

class Notifier(Protocol):

    """
    Protocol for sending notifications.

    This protocol defines the interface for notifiers. Implementations
    should provide a method `send_confirmation` that sends a confirmation
    to the customer.
    """
    def send_confirmation(seld, customer_data: CustomerData): 
        """Send a confirmation notification to the customer.

        :param customer_data: Data about the customer to notify.
        :type customer_data: CustomerData
        """
        ...

class EmailNotifier(Notifier):
    def send_confirmation(self, customer_data: CustomerData):
        #Responsabilidad de la notificacion
        from email.mime.text import MIMEText

        msg = MIMEText("Thank you for your payment.")
        msg["Subject"] = "Payment Confirmation"
        msg["From"] = "no-reply@example.com"
        msg["To"] = customer_data.contact_info.email or ""

        # server = smtplib.SMTP("localhost")
        # server.send_message(msg)
        # server.quit()
        print("Email sent to", customer_data.contact_info.email)

@dataclass
class SmsNotifier(Notifier):
    sms_gateway: str

    def send_confirmation(self, customer_data: CustomerData):
        #Responsabilidad de la notificacion
        phone_number = customer_data.contact_info.phone
        sms_gateway = "the custom SMS Gateway"
        print(
            f"send the sms using {self.sms_gateway}: SMS sent to {phone_number}: Thank you for your payment."
        )

@dataclass
class TransactionLogger:
    def log_transaction(
        self,
        customer_data: CustomerData,
        payment_data: PaymentData,
        payment_response: PaymentResponse,
    ):
        with open("transactions.log", "a") as log_file:
            log_file.write(
                f"{customer_data.name} paid {payment_data.amount}\n"
            )
            log_file.write(f"Payment status: {payment_response.status}\n")
            if payment_response.transaction_id:
                log_file.write(
                    f"Transaction ID: {payment_response.transaction_id}\n"
                )
            log_file.write(f"Message: {payment_response.message}\n")

    def log_refund(
        self, transaction_id: str, refund_response: PaymentResponse
    ):
        with open("transactions.log", "a") as log_file:
            log_file.write(
                f"Refund processed for transaction {transaction_id}\n"
            )
            log_file.write(f"Refund status: {refund_response.status}\n")
            log_file.write(f"Message: {refund_response.message}\n")


class PaymentProcessorProtocol(Protocol):
    """
    Protocol for processing payments, refunds, and recurring payments.

    This protocol defines the interface for payment processors. Implementations
    should provide methods for processing payments, refunds, and setting up recurring payments.
    """
       
    def process_transaction(self, customer_data: CustomerData, payment_data: PaymentData) -> PaymentResponse: ...

class RefundPaymentProtocol(Protocol):
    def refund_payment(self, transaction_id: str) -> PaymentResponse: ...

class RecurringPaymentProtocol(Protocol):
    def setup_recurring_payment(self, customer_data: CustomerData, payment_data: PaymentData) -> PaymentResponse: ...


class StripePaymentProcessor(PaymentProcessorProtocol, RefundPaymentProtocol, RecurringPaymentProtocol):

    def process_transaction(self, customer_data: CustomerData, payment_data: PaymentData) -> PaymentResponse:

        stripe.api_key = os.getenv("STRIPE_API_KEY")

        #Responsabilidad de procesamiento del pago
        try:
            charge = stripe.Charge.create(
                amount=payment_data.amount,
                currency="usd",
                source=payment_data.source,
                description="Charge for " + customer_data.name,
            )
            print("Payment successful")
            return PaymentResponse(
                    status=charge["status"],
                    amount=charge["amount"],
                    transaction_id=charge["id"],
                    message="Payment successful",
                )
        except StripeError as e:
            print("Payment failed:", e)
            return PaymentResponse(
                status="failed",
                amount=payment_data.amount,
                transaction_id=None,
                message=str(e),
            )
    
    def refund_payment(self, transaction_id: str) -> PaymentResponse: 
        stripe.api_key = os.getenv("STRIPE_API_KEY")
        try:
            refund = stripe.Refund.create(charge=transaction_id)
            print("Refund successful")
            return PaymentResponse(
                status=refund["status"],
                amount=refund["amount"],
                transaction_id=refund["id"],
                message="Refund successful",
            )
        except StripeError as e:
            print("Refund failed:", e)
            return PaymentResponse(
                status="failed",
                amount=0,
                transaction_id=None,
                message=str(e),
            )
    
    def setup_recurring_payment(self, customer_data: CustomerData, payment_data: PaymentData) -> PaymentResponse: 

        stripe.api_key = os.getenv("STRIPE_API_KEY")

        price_id = os.getenv("STRIPE_PRICE_ID", "")
        try:
            customer = self._get_or_create_customer(customer_data)

            payment_method = self._attach_payment_method(
                customer.id, payment_data.source
            )

            self._set_default_payment_method(customer.id, payment_method.id)

            subscription = stripe.Subscription.create(
                customer=customer.id,
                items=[
                    {"price": price_id},
                ],
                expand=["latest_invoice.payment_intent"],
            )

            print("Recurring payment setup successful")
            amount = subscription["items"]["data"][0]["price"]["unit_amount"]
            return PaymentResponse(
                status=subscription["status"],
                amount=amount,
                transaction_id=subscription["id"],
                message="Recurring payment setup successful",
            )
        except StripeError as e:
            print("Recurring payment setup failed:", e)
            return PaymentResponse(
                status="failed",
                amount=0,
                transaction_id=None,
                message=str(e),
            )
        
    def _get_or_create_customer(self, customer_data: CustomerData) -> stripe.Customer:
        """
        Creates a new customer in Stripe or retrieves an existing one.
        """
        if customer_data.customer_id:
            customer = stripe.Customer.retrieve(customer_data.customer_id)
            print(f"Customer retrieved: {customer.id}")
        else:
            if not customer_data.contact_info.email:
                raise ValueError("Email required for subscriptions")
            customer = stripe.Customer.create(
                name=customer_data.name, email=customer_data.contact_info.email
            )
            print(f"Customer created: {customer.id}")
        return customer

    def _attach_payment_method(self, customer_id: str, payment_source: str) -> stripe.PaymentMethod:
        """
        Attaches a payment method to a customer.
        """
        payment_method = stripe.PaymentMethod.retrieve(payment_source)
        stripe.PaymentMethod.attach(
            payment_method.id,
            customer=customer_id,
        )
        print(
            f"Payment method {payment_method.id} attached to customer {customer_id}"
        )
        return payment_method

    def _set_default_payment_method(self, customer_id: str, payment_method_id: str) -> None:
        """
        Sets the default payment method for a customer.
        """
        stripe.Customer.modify(
            customer_id,
            invoice_settings={
                "default_payment_method": payment_method_id,
            },
        )
        print(f"Default payment method set for customer {customer_id}")

class OfflinePaymentProcessor(PaymentProcessorProtocol):
    def process_transaction(self, customer_data: CustomerData, payment_data: PaymentData) -> PaymentResponse:

        print("Processing offline payment for: ", customer_data.name)
        return PaymentResponse(
            status= "success",
            amount= payment_data.amount,
            transaction_id= str(uuid.uuid4()),
            message= "Offline payment success"
        )

@dataclass
class PaymentService:
    customer_validator = CustomerValidator()
    payment_validator = PaymentValidator()
    payment_processor: PaymentProcessorProtocol 
    notifier: Notifier
    logger = TransactionLogger()
    recurring_processor: Optional[RecurringPaymentProtocol] = None
    refund_processor: Optional[RefundPaymentProtocol] = None

    def process_transaction(self, customer_data: CustomerData, payment_data: PaymentData) -> PaymentResponse:
        self.customer_validator.validate(customer_data)
        self.payment_validator.validate(payment_data)
        payment_response = self.payment_processor.process_transaction(
            customer_data, payment_data
        )
        self.notifier.send_confirmation(customer_data)
        self.logger.log_transaction(
            customer_data, payment_data, payment_response
        )
        return payment_response

    def process_refund(self, transaction_id: str):
        if not self.refund_processor: 
            raise Exception("This processor does not suppot refunds")
        refund_response= self.refund_processor.refund_payment(transaction_id)
        self.logger.log_refund(transaction_id, refund_response)
        return refund_response

    def setup_recurring(self, customer_data:CustomerData, payment_data: PaymentData):
        if not self.recurring_processor: 
            raise Exception("This processor does not suppot recurring")
        recurring_response= self.recurring_processor.setup_recurring_payment(customer_data, payment_data)
        self.logger.log_transaction(customer_data, payment_data, recurring_response)
        return recurring_response


if __name__ == "__main__":
     # Set up the payment processors
    stripe_processor = StripePaymentProcessor()
    offline_processor = OfflinePaymentProcessor()
    email_notifier = EmailNotifier()
    sms_notifier = SmsNotifier(gateway= "CustomGateway")
    customer_validator = CustomerValidator()
    payment_validator = PaymentValidator()
    logger = TransactionLogger()

    payment_service = PaymentService(
        payment_processor= stripe_processor,
        notifier=email_notifier,
        customer_validator= customer_validator,
        payment_validator= payment_validator,
        logger= logger,
        recurring_processor= stripe_processor,
        refund_processor= stripe_processor
    )

    second_payment_service = PaymentService(
        payment_processor= offline_processor,
        notifier=sms_notifier,
        customer_validator= customer_validator,
        payment_validator= payment_validator,
        logger= logger,
    )







    # offline_processor = OfflinePaymentProcessor()

    # customer_data_with_email =  CustomerData( name= "John Doe",
    #     contact_info= ContactInfo(email= "john@example.com")
    # )
    # customer_data_with_phone = CustomerData(name=  "Platzi Python",
    #     contact_info= ContactInfo(phone= "1234567890")
    # )

    # payment_data = PaymentData(amount=100, source= "tok_visa")

    # # Set up the notifiers
    # email_notifier = EmailNotifier()

    # sms_gateway = "YourSMSService"
    # sms_notifier = SmsNotifier(sms_gateway)

    # # # Using Stripe processor with email notifier
    # payment_service_email = PaymentService(
    #     stripe_processor,
    #     email_notifier,
    #     refund_processor=stripe_processor,
    #     recurring_processor=stripe_processor,
    # )
    # payment_service_email.process_transaction(
    #     customer_data_with_email, payment_data
    # )

    # # Using Stripe processor with SMS notifier
    # payment_service_sms = PaymentService(stripe_processor, sms_notifier)
    # sms_payment_response = payment_service_sms.process_transaction(
    #     customer_data_with_phone, payment_data
    # )

    # # Example of processing a refund using Stripe processor
    # transaction_id_to_refund = sms_payment_response.transaction_id
    # if transaction_id_to_refund:
    #     payment_service_email.process_refund(transaction_id_to_refund)

    # # Using offline processor with email notifier
    # offline_payment_service = PaymentService(offline_processor, email_notifier)
    # offline_payment_response = offline_payment_service.process_transaction(
    #     customer_data_with_email, payment_data
    # )

    # # Attempt to refund using offline processor (will fail)
    # try:
    #     if offline_payment_response.transaction_id:
    #         offline_payment_service.process_refund(
    #             offline_payment_response.transaction_id
    #         )
    # except Exception as e:
    #     print(f"Refund failed and PaymentService raised an exception: {e}")

    # # Attempt to set up recurring payment using offline processor (will fail)
    # try:
    #     offline_payment_service.setup_recurring(
    #         customer_data_with_email, payment_data
    #     )

    # except Exception as e:
    #     print(
    #         f"Recurring payment setup failed and PaymentService raised an exception {e}"
    #     )

    # try:
    #     error_payment_data = PaymentData(amount=100, source="tok_radarBlock")
    #     payment_service_email.process_transaction(
    #         customer_data_with_email, error_payment_data
    #     )
    # except Exception as e:
    #     print(f"Payment failed and PaymentService raised an exception: {e}")

    # # Set up recurrence
    # recurring_payment_data = PaymentData(amount=100, source="pm_card_visa")
    # payment_service_email.setup_recurring(
    #     customer_data_with_email, recurring_payment_data
    # )
