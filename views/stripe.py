
import stripe
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

stripe.api_key = settings.STRIPE_SECRET_KEY


def process_payment(request):
    if request.method == 'POST':
        token = request.POST.get('stripeToken')
        try:
            charge = stripe.Charge.create(
                amount=5000,  # Amount in cents (e.g., $50.00)
                currency="usd",
                source=token,
                description="Payment for Order #1234",
            )
            return render(request, 'payment_success.html')
        except stripe.error.CardError as e:
            return render(request, 'payment_failed.html')
    return render(request, 'cis/index/payment_form.html', {
        'STRIPE_PUBLISHABLE_KEY': settings.STRIPE_PUBLISHABLE_KEY
    })
process_payment.login_required = False


def create_checkout_session(request):
    print(request.user)
    
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "Example item"},
                "unit_amount": 1000,
            },
            "quantity": 1,
        }],
        success_url=request.build_absolute_uri("/success/"),
        cancel_url=request.build_absolute_uri("/cancel/"),

        # Order-level metadata on the Checkout Session (optional)
        metadata={
            "order_id": "ORD-1234-meta",
            "user_id": str(request.user.id),
        },

        # Ensure the downstream PaymentIntent carries your metadata
        payment_intent_data={
            "metadata": {
                "order_id": "ORD-1234",
                "user_id": str(request.user.id),
                "source": "checkout",
            }
        },

        # Optional: a lightweight identifier you can also use
        client_reference_id=str(request.user.id),
    )
    return JsonResponse({"id": session.id})
create_checkout_session.login_required = False

def checkout_success(request):
    return render(request, "cis/index/payment_success.html")
checkout_success.login_required = False

def checkout_cancel(request):
    return render(request, "cis/index/payment_failed.html")
checkout_cancel.login_required = False

@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig = request.META.get("HTTP_STRIPE_SIGNATURE")

    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.STRIPE_WEBHOOK_SECRET)
    except ValueError:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        print('1')
        return HttpResponse(status=400)

    if event['type'] == 'payment_intent.succeeded':
        print('PaymentIntent was successful!')
        session = event["data"]["object"]
        print(session.get("metadata"))
        print(session["amount_received"])
        print(session['id'])
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        print(session["metadata"])
        print(session["amount_received"])
        # TODO: fulfill the order using session data (e.g., session["id"], session["amount_total"])
    return HttpResponse(status=200)
stripe_webhook.login_required = False