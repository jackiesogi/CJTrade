if __name__ == "__main__":
    from cjtrade.apps.ArenaX.brokerside_server import ArenaX_BrokerSideServer

    server = ArenaX_BrokerSideServer()
    server.start()
    server.serve_forever()
