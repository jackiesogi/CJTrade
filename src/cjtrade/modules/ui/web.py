# Bootstrap HTML Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CJTrade</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        .status-card { transition: all 0.3s ease; }
        .status-card:hover { transform: translateY(-2px); }
        .status-indicator { width: 12px; height: 12px; border-radius: 50%; }
        .bg-success { background-color: #28a745 !important; }
        .bg-warning { background-color: #ffc107 !important; }
        .bg-danger { background-color: #dc3545 !important; }
    </style>
</head>
<body class="bg-light">
    <nav class="navbar navbar-dark bg-dark">
        <div class="container">
            <span class="navbar-brand mb-0 h1">
                <i class="bi bi-graph-up"></i> CJTrade
            </span>
            <span class="badge bg-{{ 'success' if status.running else 'danger' }}">
                {{ 'Running' if status.running else 'Stopped' }}
            </span>
        </div>
    </nav>

    <div class="container mt-4">
        <!-- 系統狀態概覽 -->
        <div class="row mb-4">
            <div class="col-md-3 mb-3">
                <div class="card status-card h-100">
                    <div class="card-body text-center">
                        <i class="bi bi-activity text-primary fs-1"></i>
                        <h6 class="card-title mt-2">System Status</h6>
                        <div class="d-flex align-items-center justify-content-center">
                            <div class="status-indicator bg-{{ 'success' if status.health_status == 'OK' else 'danger' }} me-2"></div>
                            <span class="text-{{ 'success' if status.health_status == 'OK' else 'danger' }}">
                                {{ status.health_status }}
                            </span>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="col-md-3 mb-3">
                <div class="card status-card h-100">
                    <div class="card-body text-center">
                        <i class="bi bi-graph-up-arrow text-info fs-1"></i>
                        <h6 class="card-title mt-2">Active Signals</h6>
                        <h4 class="text-info">{{ status.active_signals }}</h4>
                    </div>
                </div>
            </div>
            
            <div class="col-md-3 mb-3">
                <div class="card status-card h-100">
                    <div class="card-body text-center">
                        <i class="bi bi-wallet2 text-warning fs-1"></i>
                        <h6 class="card-title mt-2">Inventory Count</h6>
                        <h4 class="text-warning">{{ status.inventory_count }}</h4>
                    </div>
                </div>
            </div>
            
            <div class="col-md-3 mb-3">
                <div class="card status-card h-100">
                    <div class="card-body text-center">
                        <i class="bi bi-clock text-secondary fs-1"></i>
                        <h6 class="card-title mt-2">Last Price Update</h6>
                        <small class="text-muted">{{ status.last_price_update or 'No data' }}</small>
                    </div>
                </div>
            </div>
        </div>

        <!-- 快速操作 -->
        <div class="row mb-4">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0"><i class="bi bi-lightning"></i> Quick Operations</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-4 mb-2">
                                <button class="btn btn-primary w-100" onclick="refreshStatus()">
                                    <i class="bi bi-arrow-clockwise"></i> Refresh Status
                                </button>
                            </div>
                            <div class="col-md-4 mb-2">
                                <button class="btn btn-info w-100" onclick="viewSignals()">
                                    <i class="bi bi-list-ul"></i> View Signals
                                </button>
                            </div>
                            <div class="col-md-4 mb-2">
                                <button class="btn btn-success w-100" data-bs-toggle="modal" data-bs-target="#orderModal">
                                    <i class="bi bi-plus-circle"></i> Manual Order
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 系統日誌 -->
        <div class="row">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0"><i class="bi bi-journal-text"></i> System Log</h5>
                    </div>
                    <div class="card-body">
                        <div class="bg-dark text-light p-3 rounded" style="font-family: monospace; height: 200px; overflow-y: auto;">
                            <div id="logOutput">
                                [{{ datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') }}] System start<br>
                                [{{ datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') }}] Price monitoring running<br>
                                [{{ datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') }}] Health check normal<br>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- 手動下單 Modal -->
    <div class="modal fade" id="orderModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Manual Order</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <form id="orderForm">
                        <div class="mb-3">
                            <label for="symbol" class="form-label">Symbol</label>
                            <input type="text" class="form-control" id="symbol" placeholder="e.g. 2330">
                        </div>
                        <div class="mb-3">
                            <label for="side" class="form-label">Side</label>
                            <select class="form-select" id="side">
                                <option value="buy">Buy</option>
                                <option value="sell">Sell</option>
                            </select>
                        </div>
                        <div class="mb-3">
                            <label for="qty" class="form-label">Quantity</label>
                            <input type="number" class="form-control" id="qty" placeholder="e.g. 1000">
                        </div>
                        <div class="mb-3">
                            <label for="price" class="form-label">Price</label>
                            <input type="number" step="0.01" class="form-control" id="price" placeholder="e.g. 123.45">
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                    <button type="button" class="btn btn-primary" onclick="submitOrder()">Submit Order</button>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        function refreshStatus() {
            location.reload();
        }
        
        function viewSignals() {
            window.open('/signals', '_blank');
        }
        
        function submitOrder() {
            const formData = {
                symbol: document.getElementById('symbol').value,
                side: document.getElementById('side').value,
                qty: document.getElementById('qty').value,
                price: document.getElementById('price').value
            };
            
            fetch('/manual_order', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(formData)
            })
            .then(response => response.json())
            .then(data => {
                alert('Order submitted successfully, Order ID: ' + data.order_id);
                bootstrap.Modal.getInstance(document.getElementById('orderModal')).hide();
            })
            .catch(error => {
                alert('Error occurred while submitting order: ' + error);
            });
        }
        
        setInterval(refreshStatus, 30000);
    </script>
</body>
</html>
"""

############### Flask web server backend ################
import json
import random
import datetime
from flask import Flask, render_template_string, request, jsonify

web_app = Flask(__name__)

system_status = {
    "running": True,
    "last_price_update": None,
    "active_signals": 0,
    "inventory_count": 0,
    "health_status": "OK"
}


@web_app.route('/')
@web_app.route('/status')
def get_status():
    system_status["running"] = True
    system_status["last_price_update"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    system_status["active_signals"] = random.randint(0, 8)
    system_status["inventory_count"] = random.randint(1, 12)
    system_status["health_status"] = "OK"
    
    return render_template_string(HTML_TEMPLATE, status=system_status, datetime=datetime)

@web_app.route('/signals')
def get_signals():
    mock_signals = [
        {"symbol": "2330", "side": "buy", "price": 523.0, "score": 0.85, "time": "10:30:15"},
        {"symbol": "2317", "side": "sell", "price": 87.2, "score": 0.72, "time": "10:28:42"},
    ]
    return jsonify({"signals": mock_signals})

@web_app.route('/manual_order', methods=['POST'])
def manual_order():
    data = request.json
    return jsonify({
        "status": "received", 
        "order_id": f"ORD{random.randint(10000, 99999)}",
        "message": "Order received and queued for processing"
    })

def run_flask(host='0.0.0.0', port=5000):
    web_app.run(host=host, port=port, debug=False)
###################################################
