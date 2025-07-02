from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import db_helper
import generic_helper

app = FastAPI()
inprogress_orders = {}

@app.post("/")
async def handle_request(request: Request):
    try:
        payload = await request.json()

        # Extract necessary info from payload
        intent = payload.get('queryResult', {}).get('intent', {}).get('displayName', None)
        parameters = payload.get('queryResult', {}).get('parameters', {})

        output_contexts = payload.get('queryResult', {}).get('outputContexts', [])  # <-- fixed: [] not {}

        if output_contexts:
            session_id = generic_helper.extract_session_id(output_contexts[0]['name'])
        else:
            session_id = None  # <-- fixed: handle missing contexts

        # Intent handler mapping
        intent_handler_dict = {
            'order.add - context:ongoing-order': add_to_order,
            'track.order - context:ongoing-tracking': track_order,
            'order.complete - context:ongoing-order': complete_order,
            'order.remove - context:ongoing-order':remove_from_order
        }

        if intent in intent_handler_dict:
            handler_function = intent_handler_dict[intent]
            return await handler_function(parameters, session_id)  # session_id passed always
        else:
            return JSONResponse(status_code=400, content={"fulfillmentText": "Unknown intent"})

    except Exception as e:
        return JSONResponse(status_code=500, content={"fulfillmentText": f"Internal Server Error: {str(e)}"})

async def save_to_db(order: dict):  # <-- made async (optional improvement)
    next_order_id = db_helper.get_next_order_id()
    for food_item, quantity in order.items():
        rcode = db_helper.insert_order_item(
            food_item,
            quantity,
            next_order_id
        )
        if rcode == -1:
            return -1

    db_helper.insert_order_tracking(next_order_id, "in progress")
    return next_order_id

async def complete_order(parameters: dict, session_id: str):
    if not session_id or session_id not in inprogress_orders:
        fulfillment_text = "I'm having trouble finding your order. Sorry! Can you place a new order please?"
    else:
        order = inprogress_orders[session_id]
        order_id = await save_to_db(order)  # <-- await added because save_to_db is now async

        if order_id == -1:
            fulfillment_text = "Sorry, I couldn't process your order due to a backend error. Please place a new order again."
        else:
            order_total = db_helper.get_total_order_price(order_id)
            fulfillment_text = f"Awesome. We have placed your order. " \
                                f"Here is your order id # {order_id}. " \
                                f"Your order total is {order_total} which you can pay at the time of delivery!"

        del inprogress_orders[session_id]

    return JSONResponse(content={"fulfillmentText": fulfillment_text})

async def track_order(parameters: dict, session_id: str):  # <-- added session_id parameter
    try:
        order_id = parameters.get('order_id') or parameters.get('number')  # <-- fallback to 'number' if needed
        if not order_id:
            return JSONResponse(status_code=400, content={"fulfillmentText": "Please provide an order ID to track."})

        order_status = db_helper.get_order_status(order_id)

        if order_status:
            fulfillment_text = f"The order status for order id: {order_id} is: {order_status}"
        else:
            fulfillment_text = f"No order found with order id: {order_id}"

        return JSONResponse(content={"fulfillmentText": fulfillment_text})

    except Exception as e:
        return JSONResponse(status_code=500, content={"fulfillmentText": f"Error tracking order: {str(e)}"})

async def add_to_order(parameters: dict, session_id: str):
    try:
        food_items = parameters.get('food-item')
        quantities = parameters.get('number')

        if not food_items or not quantities:
            return JSONResponse(status_code=400, content={"fulfillmentText": "Missing food items or quantities."})

        if len(food_items) != len(quantities):
            return JSONResponse(status_code=400, content={"fulfillmentText": "Food items and quantities do not match."})
        else:
            new_food_dict = dict(zip(food_items, quantities))
            if session_id in inprogress_orders:
                current_food_dict = inprogress_orders[session_id]
                current_food_dict.update(new_food_dict)
                inprogress_orders[session_id] = current_food_dict
            else:
                inprogress_orders[session_id] = new_food_dict

            order_str = generic_helper.get_str_from_food_dict(inprogress_orders[session_id])
            fulfillment_text = f"So far you have: {order_str}. Do you need anything else?"

        return JSONResponse(content={"fulfillmentText": fulfillment_text})

    except Exception as e:
        return JSONResponse(status_code=500, content={"fulfillmentText": f"Error adding to order: {str(e)}"})
async def remove_from_order(parameters: dict, session_id: str):
    if session_id not in inprogress_orders:
        return JSONResponse(content={
            "fulfillmentText": "I'm having trouble finding your order. Sorry! Can you place a new order please?"
        })

    food_items = parameters.get("food-item", [])
    if not food_items:
        return JSONResponse(content={"fulfillmentText": "No food items provided to remove."})

    current_order = inprogress_orders[session_id]

    removed_items = []
    no_such_items = []

    for item in food_items:
        if item in current_order:
            removed_items.append(item)
            del current_order[item]
        else:
            no_such_items.append(item)

    fulfillment_text_parts = []  # Collect all parts separately

    if removed_items:
        fulfillment_text_parts.append(f"Removed {', '.join(removed_items)} from your order!")

    if no_such_items:
        fulfillment_text_parts.append(f"Your current order does not have {', '.join(no_such_items)}.")

    if not current_order:
        fulfillment_text_parts.append("Your order is now empty!")
    else:
        order_str = generic_helper.get_str_from_food_dict(current_order)
        fulfillment_text_parts.append(f"Here is what is left in your order: {order_str}.")

    fulfillment_text = " ".join(fulfillment_text_parts)

    return JSONResponse(content={
        "fulfillmentText": fulfillment_text
    })
