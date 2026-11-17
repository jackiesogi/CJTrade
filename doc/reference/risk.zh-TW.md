# 風控閘門

trading engine 在委託送到券商之前套用的事前風控：每個 bot 的資金配額、每根 K 棒的下單次數上限、重複委託的時間窗，以及虧損停損開關。每一項預設都是關閉的。

::: cjtrade.pkgs.risk.pre_trade
