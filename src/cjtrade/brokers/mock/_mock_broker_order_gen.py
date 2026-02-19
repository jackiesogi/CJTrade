from cjtrade.models.order import *

def REJECTED_ORDER_NOT_SUFFICIENT_BALANCE(order, msg="Order rejected due to insufficient balance.", metadata={}):
    return OrderResult(
        status=OrderStatus.REJECTED,
        message=msg,
        metadata=metadata,
        linked_order=order.id
    )

def REJECTED_ORDER_NOT_SUFFICIENT_STOCK(order, msg="Order rejected due to insufficient stock.", metadata={}):
    return OrderResult(
        status=OrderStatus.REJECTED,
        message=msg,
        metadata=metadata,
        linked_order=order.id
    )

def REJECTED_ORDER_EXCEED_TRADING_LIMIT(order, msg="Order rejected due to exceeding trading limit.", metadata={}):
    return OrderResult(
        status=OrderStatus.REJECTED,
        message=msg,
        metadata=metadata,
        linked_order=order.id
    )

def REJECTED_ORDER_NOT_FOUND_FOR_COMMIT(order, msg="Specified order id not found for commit.", metadata={}):
    return OrderResult(
        status=OrderStatus.REJECTED,
        message=msg,
        metadata=metadata,
        linked_order=order.id
    )

def REJECTED_ORDER_NOT_FOUND_FOR_CANCEL(order_id, msg="Specified order id not found for cancel.", metadata={}):
    return OrderResult(
        status=OrderStatus.REJECTED,
        message=msg,
        metadata=metadata,
        linked_order=order_id
    )

def REJECTED_ORDER_HAS_BEEN_FILLED(order, msg="Order cannot be cancelled because it has already been filled.", metadata={}):
    return OrderResult(
        status=OrderStatus.REJECTED,
        message=msg,
        metadata=metadata,
        linked_order=order.id
    )

####################  Standard Order Results (start)  ####################

def PLACED_ORDER_STANDARD(order, msg="Order placed successfully.", metadata={}):
    return OrderResult(
        status=OrderStatus.ON_THE_WAY,
        message=msg,
        metadata=metadata,
        linked_order=order.id
    )

def COMMITTED_ORDER_STANDARD(order, msg="Order committed successfully.", metadata={}):
    return OrderResult(
        status=OrderStatus.COMMITTED,
        message=msg,
        metadata=metadata,
        linked_order=order.id
    )

def CANCELLED_ORDER_STANDARD(order, msg="Order cancelled successfully.", metadata={}):
    return OrderResult(
        status=OrderStatus.CANCELLED,
        message=msg,
        metadata=metadata,
        linked_order=order.id
    )

####################  Standard Order Results (end)  ####################