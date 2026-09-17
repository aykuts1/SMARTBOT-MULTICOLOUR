//@version=5
strategy("Trend + ALMA9 + Tilson T3 Strategy",
     overlay=true,
     initial_capital=1000,
     default_qty_type=strategy.fixed,
     currency=currency.USD,
     commission_type=strategy.commission.percent,
     commission_value=0.055,
     pyramiding=0,
     calc_on_every_tick=true)

// =============================================================================
// PARAMETRELER (config.json ile birebir ayni)
// =============================================================================
emaFastLen    = input.int(21, "EMA Fast (Trend + Egim) Length", group="EMA / Trend")
emaSlowLen    = input.int(50, "EMA Slow Length", group="EMA / Trend")

almaLen       = input.int(9, "ALMA Length", group="ALMA")
almaOffset    = input.float(0.85, "ALMA Offset", step=0.01, group="ALMA")
almaSigma     = input.float(6.0, "ALMA Sigma", step=0.1, group="ALMA")

atrLen        = input.int(14, "ATR Length", group="ATR / Bantlar")
band1Mult     = input.float(1.5, "Bant Carpani 1", group="ATR / Bantlar")
band2Mult     = input.float(2.0, "Bant Carpani 2", group="ATR / Bantlar")
band3Mult     = input.float(3.0, "Bant Carpani 3", group="ATR / Bantlar")

t3Period      = input.int(2, "T3 Period", group="Tilson T3")
t3Factor      = input.float(0.7, "T3 Factor", step=0.01, group="Tilson T3")

positionSizePct    = input.float(8.0, "Pozisyon Buyuklugu % (bakiyenin)", group="Risk / Boyutlandirma")
leverage           = input.float(20.0, "Kaldirac", group="Risk / Boyutlandirma")
lossExitPct        = input.float(5.75, "Loss Exit % (surekli)", group="Cikis Esikleri")
candleCloseLossPct = input.float(4.0, "Mum Kapanis Zarar %", group="Cikis Esikleri")
profitThreshPct    = input.float(0.10, "Kar Esigi % (renk-flip / TP bandi)", step=0.01, group="Cikis Esikleri")

// =============================================================================
// HESAPLAMALAR
// =============================================================================
emaFast = ta.ema(close, emaFastLen)
emaSlow = ta.ema(close, emaSlowLen)
almaVal = ta.alma(close, almaLen, almaOffset, almaSigma)   // sadece TP bantlari icin
atrVal  = ta.atr(atrLen)

// Trend: EMA21, EMA50'ye gore (eski mantiga donuldu)
trendLong  = emaFast > emaSlow
trendShort = emaFast < emaSlow

slopeLong  = emaFast > emaFast[1]
slopeShort = emaFast < emaFast[1]

almaUpper1 = almaVal + atrVal * band1Mult
almaLower1 = almaVal - atrVal * band1Mult
almaUpper2 = almaVal + atrVal * band2Mult
almaLower2 = almaVal - atrVal * band2Mult
almaUpper3 = almaVal + atrVal * band3Mult
almaLower3 = almaVal - atrVal * band3Mult

b  = t3Factor
c1 = -b*b*b
c2 = 3*b*b + 3*b*b*b
c3 = -6*b*b - 3*b - 3*b*b*b
c4 = 1 + 3*b + b*b*b + 3*b*b

e1 = ta.ema(close, t3Period)
e2 = ta.ema(e1, t3Period)
e3 = ta.ema(e2, t3Period)
e4 = ta.ema(e3, t3Period)
e5 = ta.ema(e4, t3Period)
e6 = ta.ema(e5, t3Period)
t3 = c1*e6 + c2*e5 + c3*e4 + c4*e3

t3Green = t3 > t3[1]
t3Red   = t3 < t3[1]

longSignal  = t3Green and trendLong  and slopeLong
shortSignal = t3Red   and trendShort and slopeShort

// En yakin ALMA bandi -- entryPx'e gore secilir
nearestLowerBand(entryPx) =>
    float belowMax = na
    if almaLower1 < entryPx
        belowMax := na(belowMax) ? almaLower1 : math.max(belowMax, almaLower1)
    if almaLower2 < entryPx
        belowMax := na(belowMax) ? almaLower2 : math.max(belowMax, almaLower2)
    if almaLower3 < entryPx
        belowMax := na(belowMax) ? almaLower3 : math.max(belowMax, almaLower3)
    na(belowMax) ? math.min(math.min(almaLower1, almaLower2), almaLower3) : belowMax

nearestUpperBand(entryPx) =>
    float aboveMin = na
    if almaUpper1 > entryPx
        aboveMin := na(aboveMin) ? almaUpper1 : math.min(aboveMin, almaUpper1)
    if almaUpper2 > entryPx
        aboveMin := na(aboveMin) ? almaUpper2 : math.min(aboveMin, almaUpper2)
    if almaUpper3 > entryPx
        aboveMin := na(aboveMin) ? almaUpper3 : math.min(aboveMin, almaUpper3)
    na(aboveMin) ? math.max(math.max(almaUpper1, almaUpper2), almaUpper3) : aboveMin

// =============================================================================
// POZISYON TAKIBI
// =============================================================================
var float entryPriceRec = na
var float tpBandRec     = na

inLong  = strategy.position_size > 0
inShort = strategy.position_size < 0
prevSide = inLong ? "long" : inShort ? "short" : na

trendFlipHit = (prevSide == "short" and trendLong) or (prevSide == "long" and trendShort)

candleCloseLossHit = prevSide == "short" ? (close - entryPriceRec) / entryPriceRec * 100.0 >= candleCloseLossPct :
     prevSide == "long" ? (entryPriceRec - close) / entryPriceRec * 100.0 >= candleCloseLossPct : false

colorFlipProfitHit = prevSide == "short" and t3Green ? (entryPriceRec - close) / entryPriceRec * 100.0 >= profitThreshPct :
     prevSide == "long" and t3Red ? (close - entryPriceRec) / entryPriceRec * 100.0 >= profitThreshPct : false

// =============================================================================
// GIRIS / CIKIS EMIRLERI (mum kapanisinda)
// =============================================================================
qty = strategy.equity * (positionSizePct / 100.0) * leverage / close

if barstate.isconfirmed
    if inShort or inLong
        if trendFlipHit
            strategy.close_all(comment="trend_flip")
        else if candleCloseLossHit
            strategy.close_all(comment="candle_close_loss")
        else if colorFlipProfitHit
            strategy.close_all(comment="color_flip_profit")
        else
            tpBandRec := inShort ? nearestLowerBand(entryPriceRec) : nearestUpperBand(entryPriceRec)

    if strategy.position_size == 0
        if longSignal
            strategy.entry("Long", strategy.long, qty=qty, comment="entry_long")
            entryPriceRec := close
            tpBandRec := nearestUpperBand(close)
        else if shortSignal
            strategy.entry("Short", strategy.short, qty=qty, comment="entry_short")
            entryPriceRec := close
            tpBandRec := nearestLowerBand(close)

// =============================================================================
// SUREKLI (intrabar) KONTROLLER -- Loss Exit ve ALMA TP bandi
// =============================================================================
if strategy.position_size != 0
    stopPrice = inLong ? entryPriceRec * (1 - lossExitPct / 100.0) : entryPriceRec * (1 + lossExitPct / 100.0)

    bandProfitPct = inLong ? (tpBandRec - entryPriceRec) / entryPriceRec * 100.0 :
                              (entryPriceRec - tpBandRec) / entryPriceRec * 100.0
    tpArmed = not na(tpBandRec) and bandProfitPct >= profitThreshPct

    if inLong
        strategy.exit("TP/SL Long", from_entry="Long", stop=stopPrice, limit=tpArmed ? tpBandRec : na, comment_loss="loss_exit", comment_profit="take_profit")
    if inShort
        strategy.exit("TP/SL Short", from_entry="Short", stop=stopPrice, limit=tpArmed ? tpBandRec : na, comment_loss="loss_exit", comment_profit="take_profit")

// =============================================================================
// BASARILI / BASARISIZ ISLEM BOYAMA (giris-cikis mumlari arasi)
// =============================================================================
var int paintedTrades = 0

if strategy.closedtrades > paintedTrades
    for i = paintedTrades to strategy.closedtrades - 1
        entryBar    = strategy.closedtrades.entry_bar_index(i)
        exitBar     = strategy.closedtrades.exit_bar_index(i)
        entryPx     = strategy.closedtrades.entry_price(i)
        exitPx      = strategy.closedtrades.exit_price(i)
        tradeProfit = strategy.closedtrades.profit(i)
        boxColor = tradeProfit > 0 ? color.new(color.green, 80) : color.new(color.red, 80)
        box.new(left=entryBar, right=exitBar, top=math.max(entryPx, exitPx), bottom=math.min(entryPx, exitPx),
             bgcolor=boxColor, border_color=boxColor, xloc=xloc.bar_index)
    paintedTrades := strategy.closedtrades

// =============================================================================
// CIZIM
// =============================================================================
plot(emaFast, "EMA21 (Trend + Egim)", color=color.gray)
plot(emaSlow, "EMA50", color=color.orange)
plot(almaVal, "ALMA9 (TP referans)", color=color.blue, linewidth=2)
plot(t3, "Tilson T3", color=t3Green ? color.green : color.red, linewidth=2)
