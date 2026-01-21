import requests
from django.shortcuts import render, get_object_or_404, redirect
from .models import Product, Category, Order, OrderItem
from .cart import Cart
from django.core.mail import send_mail
from django.conf import settings
from django.core.paginator import Paginator
from django.http import HttpResponse

def payment_success(request):
    # Clear cart
    request.session["cart"] = {}
    return render(request, "shop/payment_success.html")

def create_bitcoin_payment(request):
    cart = request.session.get("cart", {})

    if not cart:
        return redirect("cart_detail")  # No items in cart

    # Calculate total USD
    total = round(
        sum(float(item["price"]) * int(item["quantity"]) for item in cart.values()), 2
    )

    url = "https://api.nowpayments.io/v1/invoice"

    headers = {
        "x-api-key": settings.NOWPAYMENTS_API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "price_amount": total,
        "price_currency": "usd",
        "pay_currency": "btc",
        "order_id": "order_" + str(request.session.session_key),
        "order_description": "PokéStore Order",
        "ipn_callback_url": request.build_absolute_uri("/payment-success/"),
        "success_url": request.build_absolute_uri("/payment-success/"),
        "cancel_url": request.build_absolute_uri("/cart/")
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        # Redirect user to the hosted invoice page
        return redirect(data["invoice_url"])
    except requests.exceptions.RequestException as e:
        return HttpResponse(f"Error contacting NowPayments: {e}")


def home(request):
    featured = Product.objects.filter(available=True).order_by('-created')[:6]
    categories = Category.objects.all()
    context = {'featured': featured, 'categories': categories}
    return render(request, 'shop/home.html', context)

def product_list(request, category_slug=None):
    category = None
    categories = Category.objects.all()
    products = Product.objects.filter(available=True)

    q = request.GET.get('q')
    if q:
        products = products.filter(name__icontains=q)

    if category_slug:
        category = get_object_or_404(Category, slug=category_slug)
        products = products.filter(category=category)

    paginator = Paginator(products, 12)
    page = request.GET.get('page')
    products_page = paginator.get_page(page)

    return render(request, 'shop/product_list.html', {
        'category': category,
        'categories': categories,
        'products': products_page,
        'query': q
    })

def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug, available=True)
    categories = Category.objects.all()
    return render(request, 'shop/product_detail.html', {'product': product, 'categories': categories})

def cart_add(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    qty = int(request.POST.get('quantity', 1)) if request.method == 'POST' else 1
    cart.add(product=product, quantity=qty)
    return redirect('cart_detail')

def cart_remove(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    cart.remove(product)
    return redirect('cart_detail')

def cart_detail(request):
    cart = Cart(request)
    return render(request, 'shop/cart.html', {'cart': cart})

def checkout(request):
    cart = Cart(request)
    if len(cart) == 0:
        return redirect('product_list')

    if request.method == 'POST':
        full_name = request.POST.get('full_name')
        email = request.POST.get('email')
        address = request.POST.get('address')

        # Create order
        order = Order.objects.create(
            full_name=full_name,
            email=email,
            address=address,
            total=cart.get_total_price()
        )

        # Create order items and reduce stock
        items_text = ""
        for item in cart:
            product = item['product']
            OrderItem.objects.create(
                order=order,
                product=product,
                price=item['price'],
                quantity=item['quantity']
            )
            if product.stock >= item['quantity']:
                product.stock -= item['quantity']
                product.save()
            items_text += f"{item['quantity']} x {product.name} at {item['price']} $\n"

        # Send email notification to store owner
        subject = f"New Order #{order.id} from {full_name}"
        message = f"""
You have a new order!

Order ID: {order.id}
Customer Name: {full_name}
Customer Email: {email}
Customer Address: {address}

Order Items:
{items_text}

Total: {order.total} $
"""
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [settings.EMAIL_HOST_USER],  # send to yourself
            fail_silently=False,
        )

        # Clear cart and render thank-you page without showing user email
        cart.clear()
        return render(request, 'shop/checkout_complete.html')

    return render(request, 'shop/checkout.html', {'cart': cart})
