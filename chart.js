class CandleChart {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) {
            throw new Error(`Canvas with ID "${canvasId}" not found.`);
        }
        this.ctx = this.canvas.getContext('2d');
        this.historical = [];
        this.liveCandle = null;
        this.zigzag = [];
        this.divergences = [];
        this.minGap = 0.5;
        this.minCandleWidth = 1;
        this.mouseX = null;
        this.mouseY = null;
        this.isDragging = false;
        this.lastX = 0;
        this.lastY = 0;
        this.dragMode = null;
        this.viewport = { candleStartIndex: 0, candleCount: 50, minPrice: 0, maxPrice: 100 };
        this.centerPrice = 0;
        this.visibleRange = 1;
        this.minVisibleRange = 0.01;
        this.maxVisibleRange = 1e9;
        this.minCandles = 10;
        this.maxCandles = 300;
        this.initialized = false;

        this.resizeCanvas();
        window.addEventListener('resize', this.resizeCanvas.bind(this));
        this.canvas.addEventListener('mousemove', this.handleMouseMove.bind(this));
        this.canvas.addEventListener('mouseout', this.handleMouseOut.bind(this));
        this.canvas.addEventListener('wheel', this.handleWheel.bind(this));
        this.canvas.addEventListener('mousedown', this.handleMouseDown.bind(this));
        this.canvas.addEventListener('mouseup', this.handleMouseUp.bind(this));
        this.canvas.addEventListener('dblclick', this.resetViewport.bind(this));
    }

    resizeCanvas() {
        this.canvas.width = window.innerWidth;
        this.canvas.height = window.innerHeight;
        if (this.historical.length > 0 || this.liveCandle) {
            this.draw();
        }
    }

    setData(historical, liveCandle, zigzag, divergences) {
        const oldLength = this.historical.length + (this.liveCandle ? 1 : 0);
        this.historical = historical;
        this.liveCandle = liveCandle;
        this.zigzag = zigzag || [];
        this.divergences = divergences || [];
        const newLength = historical.length + (liveCandle ? 1 : 0);
        if (newLength > oldLength) {
            this.viewport.candleStartIndex += (newLength - oldLength);
        }
        this.viewport.candleStartIndex = Math.max(0, Math.min(newLength - this.viewport.candleCount, this.viewport.candleStartIndex));
        if (!this.initialized) {
            this.updateViewport({ reset: true });
            this.initialized = true;
        } else {
            this.updateViewport({ reset: false });
        }
        this.draw();
    }

    handleMouseDown(event) {
        if (event.button === 0) {
            event.preventDefault();
            this.isDragging = true;
            this.lastX = event.clientX;
            this.lastY = event.clientY;
            const rect = this.canvas.getBoundingClientRect();
            const relativeX = event.clientX - rect.left;
            this.dragMode = relativeX > this.canvas.width - 100 ? "zoom" : "pan";
        }
    }

    handleMouseUp() {
        this.isDragging = false;
        this.dragMode = null;
    }

    handleMouseMove(event) {
        const rect = this.canvas.getBoundingClientRect();
        this.mouseX = event.clientX - rect.left;
        this.mouseY = event.clientY - rect.top;
        if (this.isDragging) {
            const deltaX = event.clientX - this.lastX;
            const deltaY = this.lastY - event.clientY;
            const pricePerPixel = this.visibleRange / (this.canvas.height - 50);
            if (this.dragMode === "zoom") {
                const zoomChange = Math.exp(deltaY * 0.005);
                this.visibleRange /= zoomChange;
                this.visibleRange = Math.max(this.minVisibleRange, Math.min(this.maxVisibleRange, this.visibleRange));
            } else if (this.dragMode === "pan") {
                const deltaPrice = deltaY * pricePerPixel;
                this.centerPrice += deltaPrice;
                this.viewport.candleStartIndex -= deltaX * (this.viewport.candleCount / (this.canvas.width - 100));
                this.viewport.candleStartIndex = Math.max(0, Math.min(this.historical.length - this.viewport.candleCount, this.viewport.candleStartIndex));
            }
            this.lastX = event.clientX;
            this.lastY = event.clientY;
            this.updateViewport({ reset: false });
        }
        this.draw();
    }

    handleMouseOut() {
        this.mouseX = null;
        this.mouseY = null;
        this.draw();
    }

    handleWheel(event) {
        event.preventDefault();
        const delta = Math.sign(event.deltaY);
        const oldCandleCount = this.viewport.candleCount;
        this.viewport.candleCount += delta * 10;
        this.viewport.candleCount = Math.max(this.minCandles, Math.min(this.maxCandles, this.viewport.candleCount));
        const historicalLength = this.historical.length;
        if (this.liveCandle) {
            this.viewport.candleStartIndex = Math.max(0, historicalLength - this.viewport.candleCount + 1);
        } else {
            this.viewport.candleStartIndex = Math.max(0, Math.min(historicalLength - this.viewport.candleCount, this.viewport.candleStartIndex));
        }
        this.updateViewport({ reset: false });
        this.draw();
    }

    resetViewport() {
        this.updateViewport({ reset: true });
        this.draw();
    }

    updateViewport({ reset = false } = {}) {
        const historical = this.historical;
        const liveCandle = this.liveCandle;
        let displayData = historical.slice(this.viewport.candleStartIndex, this.viewport.candleStartIndex + this.viewport.candleCount);
        if (liveCandle && this.viewport.candleStartIndex + this.viewport.candleCount > historical.length) {
            displayData.push(liveCandle);
        }
        if (displayData.length === 0) {
            this.viewport.minPrice = 0;
            this.viewport.maxPrice = 100;
            this.centerPrice = 50;
            this.visibleRange = 100;
            return;
        }
        const prices = displayData.flatMap(d => [d.high, d.low]).filter(p => !isNaN(p));
        if (prices.length === 0) {
            this.viewport.minPrice = 0;
            this.viewport.maxPrice = 100;
            this.centerPrice = 50;
            this.visibleRange = 100;
            return;
        }
        const baseMinPrice = Math.min(...prices);
        const baseMaxPrice = Math.max(...prices);
        const baseRange = baseMaxPrice - baseMinPrice || 1;
        const margin = baseRange * 0.1;
        if (reset) {
            this.centerPrice = (baseMaxPrice + baseMinPrice) / 2;
            this.visibleRange = baseRange + 2 * margin;
        } else {
            const requiredMin = baseMinPrice - margin;
            const requiredMax = baseMaxPrice + margin;
            if (requiredMin < this.viewport.minPrice) {
                const delta = this.viewport.minPrice - requiredMin;
                this.visibleRange += delta;
                this.centerPrice -= delta / 2;
            }
            if (requiredMax > this.viewport.maxPrice) {
                const delta = requiredMax - this.viewport.maxPrice;
                this.visibleRange += delta;
                this.centerPrice += delta / 2;
            }
        }
        this.viewport.minPrice = this.centerPrice - this.visibleRange / 2;
        this.viewport.maxPrice = this.centerPrice + this.visibleRange / 2;
    }

    draw() {
        let data = [...this.historical];
        if (this.liveCandle) {
            data.push(this.liveCandle);
        }
        if (data.length === 0) {
            this.ctx.fillStyle = "#ffffff";
            this.ctx.font = "16px Arial";
            this.ctx.textAlign = "center";
            this.ctx.fillText("No data available", this.canvas.width / 2, this.canvas.height / 2);
            return;
        }

        this.ctx.fillStyle = "#191a20";
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

        const startIndex = Math.round(this.viewport.candleStartIndex);
        let displayData = data.slice(startIndex, startIndex + this.viewport.candleCount);
        const chartWidth = this.canvas.width - 100;
        const chartHeight = this.canvas.height - 30;
        const volumeHeight = chartHeight * 0.2;
        const priceChartHeight = chartHeight - volumeHeight;
        const gapFactor = 0.4;
        const totalWidthPerCandle = chartWidth / displayData.length;
        const gap = Math.max(this.minGap, totalWidthPerCandle * gapFactor);
        let candleWidth = totalWidthPerCandle - gap;
        candleWidth = Math.max(this.minCandleWidth, candleWidth);

        const priceRange = this.viewport.maxPrice - this.viewport.minPrice || 1;
        const scaleY = (price) => {
            if (isNaN(price)) return NaN;
            let y = priceChartHeight - ((price - this.viewport.minPrice) / priceRange) * priceChartHeight + 20;
            return Math.max(20, Math.min(y, priceChartHeight + 20));
        };
        const getPriceFromY = (y) => {
            return this.viewport.minPrice + (1 - (y - 20) / priceChartHeight) * priceRange;
        };
        const getCandleIndexFromX = (x) => {
            const index = Math.floor((x - 10) / (candleWidth + gap));
            return (index >= 0 && index < displayData.length) ? index : null;
        };
        const volumes = displayData.map(d => d.volume || 0).filter(v => !isNaN(v));
        const maxVolume = Math.max(...volumes, 1);
        const scaleVolume = (volume) => {
            if (isNaN(volume)) return chartHeight;
            return chartHeight - (volume / maxVolume) * volumeHeight;
        };

        // Volume bars
        displayData.forEach((candle, index) => {
            const x = index * (candleWidth + gap) + 10;
            const volume = candle.volume || 0;
            const volumeY = scaleVolume(volume);
            this.ctx.fillStyle = candle.close >= candle.open ? "rgba(45, 189, 133, 0.4)" : "rgba(246, 70, 93, 0.4)";
            if (!isNaN(volumeY) && volumeY <= chartHeight) {
                this.ctx.fillRect(x, volumeY, candleWidth, chartHeight - volumeY);
            }
        });

        // Candles
        displayData.forEach((candle, index) => {
            const x = index * (candleWidth + gap) + 10;
            const openY = scaleY(candle.open);
            const closeY = scaleY(candle.close);
            const highY = scaleY(candle.high);
            const lowY = scaleY(candle.low);
            if (isNaN(openY) || isNaN(closeY) || isNaN(highY) || isNaN(lowY)) return;
            const bodyColor = candle.close >= candle.open ? "#2dbd85" : "#f6465d";
            this.ctx.beginPath();
            this.ctx.moveTo(x + candleWidth / 2, highY);
            this.ctx.lineTo(x + candleWidth / 2, lowY);
            this.ctx.strokeStyle = bodyColor;
            this.ctx.stroke();
            this.ctx.fillStyle = bodyColor;
            const bodyY = Math.min(openY, closeY);
            const bodyHeight = Math.abs(openY - closeY) || 1;
            this.ctx.fillRect(x, bodyY, candleWidth, bodyHeight);
        });

        // ZigZag-Linie
        if (this.zigzag.length > 1) {
            this.ctx.beginPath();
            this.ctx.strokeStyle = "#FFD700"; // Gelb für ZigZag-Linie
            this.ctx.lineWidth = 2;
            this.zigzag.forEach((point, i) => {
                const dataIndex = point.index - startIndex;
                if (dataIndex >= 0 && dataIndex < displayData.length) {
                    const x = dataIndex * (candleWidth + gap) + 10 + candleWidth / 2;
                    const y = scaleY(point.value);
                    if (isNaN(y)) return;
                    if (i === 0) {
                        this.ctx.moveTo(x, y);
                    } else {
                        this.ctx.lineTo(x, y);
                    }
                    // Marker für Swing-Punkte
                    this.ctx.fillStyle = point.type === 'peak' ? "#00FF00" : "#FF0000"; // Grün für Peaks, Rot für Lows
                    this.ctx.beginPath();
                    this.ctx.arc(x, y, 5, 0, 2 * Math.PI);
                    this.ctx.fill();
                    // Label für Swing-Punkte
                    this.ctx.fillStyle = "#FFFFFF";
                    this.ctx.font = "12px Arial";
                    this.ctx.textAlign = "center";
                    this.ctx.fillText(point.label, x, y - 10);
                }
            });
            this.ctx.stroke();
        }

        // RSI-Divergenzen als Linien
        if (this.divergences.length > 0) {
            this.divergences.forEach((div) => {
                const startDataIndex = div.startIndex - startIndex;
                const endDataIndex = div.endIndex - startIndex;
                if (startDataIndex >= 0 && startDataIndex < displayData.length && endDataIndex >= 0 && endDataIndex < displayData.length) {
                    const startX = startDataIndex * (candleWidth + gap) + 10 + candleWidth / 2;
                    const endX = endDataIndex * (candleWidth + gap) + 10 + candleWidth / 2;
                    const startY = scaleY(div.startPrice);
                    const endY = scaleY(div.endPrice);
                    if (isNaN(startY) || isNaN(endY)) return;
                    this.ctx.beginPath();
                    this.ctx.strokeStyle = (div.type.includes('bullish')) ? "#00FF00" : "#FF0000"; // Grün für bullish, Rot für bearish
                    this.ctx.lineWidth = 2;
                    this.ctx.setLineDash([5, 5]); // Gestrichelte Linie für Divergenzen
                    this.ctx.moveTo(startX, startY);
                    this.ctx.lineTo(endX, endY);
                    this.ctx.stroke();
                    // Label für Divergenz (am Ende der Linie)
                    this.ctx.fillStyle = "#FFFFFF";
                    this.ctx.font = "12px Arial";
                    this.ctx.textAlign = "left";
                    const label = div.type.replace('_', ' ').charAt(0).toUpperCase() + div.type.replace('_', ' ').slice(1) + ' Div';
                    this.ctx.fillText(label, endX + 5, endY);
                }
            });
            this.ctx.setLineDash([]); // Reset zu solider Linie
        }

        // Price labels
        this.ctx.fillStyle = "#ffffff";
        this.ctx.font = "12px Arial";
        this.ctx.textAlign = "right";
        for (let i = 0; i <= 5; i++) {
            const price = this.viewport.minPrice + (priceRange * i) / 5;
            const y = scaleY(price);
            if (isNaN(y)) continue;
            this.ctx.fillText(price.toFixed(2), this.canvas.width - 5, y + 5);
        }

        // Time labels
        this.ctx.textAlign = "left";
        displayData.forEach((candle, index) => {
            if (index % Math.ceil(displayData.length / 10) === 0) {
                const x = index * (candleWidth + gap) + 10 + candleWidth / 2;
                const timeStr = this.formatTime(candle.time);
                this.ctx.fillText(timeStr, x - 20, chartHeight + 20);
            }
        });

        // Crosshair
        if (this.mouseX !== null && this.mouseY !== null && this.mouseX >= 10 && this.mouseX <= chartWidth + 10 && this.mouseY >= 20 && this.mouseY <= chartHeight + 20) {
            if (this.mouseY <= priceChartHeight + 20) {
                this.ctx.beginPath();
                this.ctx.setLineDash([2, 2]);
                this.ctx.lineWidth = 1;
                this.ctx.strokeStyle = "#ffffff";
                this.ctx.moveTo(10, this.mouseY);
                this.ctx.lineTo(this.canvas.width - 50, this.mouseY);
                this.ctx.stroke();
                const price = getPriceFromY(this.mouseY);
                if (!isNaN(price)) {
                    const priceText = price.toFixed(2);
                    const textWidth = this.ctx.measureText(priceText).width + 10;
                    let labelX = Math.min(this.canvas.width - 5, this.canvas.width - textWidth);
                    // Simple overlap avoidance: shift if near other labels
                    labelX = Math.max(labelX, this.mouseX + 10); // Example shift
                    this.ctx.fillStyle = "#ffffff";
                    this.ctx.fillRect(labelX, this.mouseY - 10, textWidth, 20);
                    this.ctx.fillStyle = "#000000";
                    this.ctx.font = "12px Arial";
                    this.ctx.textAlign = "right";
                    this.ctx.fillText(priceText, labelX + textWidth - 5, this.mouseY + 5);
                }
            }
            this.ctx.beginPath();
            this.ctx.strokeStyle = "#ffffff";
            this.ctx.moveTo(this.mouseX, 20);
            this.ctx.lineTo(this.mouseX, chartHeight);
            this.ctx.stroke();
            const index = getCandleIndexFromX(this.mouseX);
            if (index !== null) {
                const candle = displayData[index];
                const timeStr = this.formatTime(candle.time);
                const textWidth = this.ctx.measureText(timeStr).width + 5;
                const textX = Math.max(10, Math.min(this.mouseX - textWidth / 2, chartWidth - textWidth + 10));
                this.ctx.fillStyle = "#ffffff";
                this.ctx.fillRect(textX, chartHeight + 5, textWidth, 20);
                this.ctx.fillStyle = "#000000";
                this.ctx.font = "12px Arial";
                this.ctx.textAlign = "left";
                this.ctx.fillText(timeStr, textX + 2, chartHeight + 20);
                const isLive = this.liveCandle && index === displayData.length - 1;
                const ohlcv = `O: ${candle.open.toFixed(2)} H: ${candle.high.toFixed(2)} L: ${candle.low.toFixed(2)} C: ${candle.close.toFixed(2)} Vol: ${candle.volume.toFixed(0)} ${isLive ? "(Live)" : ""}`;
                this.ctx.font = "16px Arial";
                this.ctx.fillStyle = "#ffffff";
                this.ctx.textAlign = "left";
                this.ctx.fillText(ohlcv, 10, 30);
            }
        }
        this.ctx.setLineDash([]);
    }

    formatTime(timestamp) {
        const date = new Date(timestamp);
        return `${date.toLocaleDateString()} ${date.getHours().toString().padStart(2, "0")}:${date.getMinutes().toString().padStart(2, "0")}`;
    }
}