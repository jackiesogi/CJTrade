## Broker backend and broker-specific implementation

In `cjtrade` project, we aimed to provide an unified programming interface for trading system, thus we try our best to maintain the code in this directory, which serves as the backend to the real call provided by different securities brokers.

Each broker's implementation should inherit the base class defined in `broker_base.py`.