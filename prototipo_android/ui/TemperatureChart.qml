import QtQuick
import QtQuick.Controls

Rectangle {
    id: chart
    objectName: "temperatureChart"
    color: "white"
    radius: 16
    border.color: "#dce6ed"
    property var info: ({loaded: false})
    property real viewStart: 0
    property real viewEnd: 1
    property var selected: ({})
    property bool showPrincipal: true
    property bool showSetpoint: true
    property bool showDoor: false
    onShowPrincipalChanged: canvas.requestPaint()
    onShowSetpointChanged: canvas.requestPaint()
    onShowDoorChanged: canvas.requestPaint()
    signal recordSelected(var record)

    function reset() {
        selected = ({})
        if (info.loaded) setView(info.start, Math.max(info.end, info.start + 1000))
        else canvas.requestPaint()
    }
    function setView(start, end) {
        if (!info.loaded) return
        let fullEnd = Math.max(info.end, info.start + 1000)
        let fullSpan = fullEnd - info.start
        let span = Math.max(Math.min(1000, fullSpan), Math.min(fullSpan, end - start))
        let left = Math.max(info.start, Math.min(fullEnd - span, start))
        viewStart = left
        viewEnd = left + span
        canvas.requestPaint()
    }
    function zoom(factor, fraction) {
        let pivot = viewStart + (viewEnd - viewStart) * fraction
        let span = (viewEnd - viewStart) / factor
        setView(pivot - span * fraction, pivot + span * (1 - fraction))
    }
    function pick(fraction) {
        if (!info.loaded) return
        selected = backend.recordAt(viewStart + (viewEnd - viewStart) * Math.max(0, Math.min(1, fraction)))
        recordSelected(selected)
        canvas.requestPaint()
    }
    onInfoChanged: reset()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()

    Text {
        anchors { left: parent.left; top: parent.top; margins: 18 }
        text: "TEMPERATURA • °C"
        color: "#537087"
        font { pixelSize: 12; bold: true; letterSpacing: 1 }
    }
    Canvas {
        id: canvas
        anchors.fill: parent
        onPaint: {
            let ctx = getContext("2d")
            ctx.reset()
            let width = canvas.width - 76, height = canvas.height - 90
            ctx.translate(54, 50)
            if (!chart.info.loaded || width <= 0 || height <= 0) return
            let points = backend.plotPoints(chart.viewStart, chart.viewEnd, Math.floor(width))
            let valid = points.filter(p => p.y !== null && isFinite(p.y))
            if (!valid.length) {
                ctx.fillStyle = "#537087"
                ctx.font = "14px sans-serif"
                ctx.fillText("Sem temperaturas válidas neste período.", 12, 32)
                return
            }
            let values = valid.map(p => p.y)
            if (chart.showSetpoint) values = values.concat(points.filter(p => p.setpoint !== null && isFinite(p.setpoint)).map(p => p.setpoint))
            let low = Math.min(...values), high = Math.max(...values)
            let pad = Math.max(0.5, (high - low) * 0.12)
            low -= pad; high += pad
            let px = x => (x - chart.viewStart) / (chart.viewEnd - chart.viewStart) * width
            let py = y => height - (y - low) / (high - low) * height
            ctx.font = "12px sans-serif"
            for (let i = 0; i <= 4; i++) {
                let y = i * height / 4
                ctx.strokeStyle = "#eaf0f4"; ctx.lineWidth = 1
                ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke()
                ctx.fillStyle = "#698296"
                ctx.fillText((high - i * (high-low) / 4).toFixed(1), -46, y + 4)
            }
            for (let i = 0; i <= 3; i++) {
                let x = i * width / 3
                let date = new Date(chart.viewStart + i * (chart.viewEnd-chart.viewStart) / 3)
                let text = Qt.formatDateTime(date, "dd/MM HH:mm")
                ctx.fillStyle = "#698296"
                ctx.fillText(text, Math.max(0, Math.min(width-82, x-38)), height+24)
            }
            ctx.save()
            ctx.beginPath(); ctx.rect(0, 0, width, height); ctx.clip()
            for (let limit of [chart.info.low, chart.info.high]) {
                if (limit >= low && limit <= high) {
                    ctx.strokeStyle = "#e8a35b"; ctx.lineWidth = 1
                    ctx.setLineDash([5, 4]); ctx.beginPath()
                    ctx.moveTo(0, py(limit)); ctx.lineTo(width, py(limit)); ctx.stroke()
                }
            }
            ctx.setLineDash([])
            ctx.strokeStyle = "#07998f"; ctx.lineWidth = 2.5
            ctx.beginPath()
            let connected = false
            for (let p of points) {
                if (p.y === null || !isFinite(p.y)) { connected = false; continue }
                if (!connected) ctx.moveTo(px(p.x), py(p.y))
                else ctx.lineTo(px(p.x), py(p.y))
                connected = true
            }
            if (chart.showPrincipal) ctx.stroke()
            if (chart.showPrincipal && valid.length === 1) {
                ctx.fillStyle = "#07998f"; ctx.beginPath()
                ctx.arc(px(valid[0].x), py(valid[0].y), 4, 0, 2*Math.PI); ctx.fill()
            }
            if (chart.showSetpoint) {
                ctx.strokeStyle = "#497cdb"; ctx.lineWidth = 2; ctx.beginPath()
                let connected = false
                for (let point of points) {
                    if (point.setpoint === null || !isFinite(point.setpoint)) { connected = false; continue }
                    if (connected) ctx.lineTo(px(point.x), py(point.setpoint))
                    else ctx.moveTo(px(point.x), py(point.setpoint))
                    connected = true
                }
                ctx.stroke()
            }
            if (chart.showDoor) {
                ctx.strokeStyle = "#a06cc0"; ctx.lineWidth = 2; ctx.beginPath()
                let previous = null
                for (let point of points) {
                    if (point.door === null) { previous = null; continue }
                    let y = height - 8 - point.door * 20
                    if (previous !== null) { ctx.lineTo(px(point.x), previous); ctx.lineTo(px(point.x), y) }
                    else ctx.moveTo(px(point.x), y)
                    previous = y
                }
                ctx.stroke()
                ctx.fillStyle = "#a06cc0"; ctx.fillText("Porta: faixa inferior 0/1", 8, height-36)
            }
            if (chart.selected.x !== undefined && chart.selected.y !== null) {
                let sx = px(chart.selected.x), sy = py(chart.selected.y)
                ctx.strokeStyle = "#d78c2f"; ctx.lineWidth = 1
                ctx.beginPath(); ctx.moveTo(sx, 0); ctx.lineTo(sx, height); ctx.stroke()
                ctx.fillStyle = "#d78c2f"; ctx.beginPath(); ctx.arc(sx, sy, 5, 0, 2*Math.PI); ctx.fill()
            }
            ctx.restore()
        }
    }
    Item {
        id: interaction
        anchors.fill: parent
        anchors { topMargin: 50; bottomMargin: 40; leftMargin: 54; rightMargin: 22 }
        TapHandler {
            onTapped: (eventPoint) => chart.pick(eventPoint.position.x / interaction.width)
        }
        DragHandler {
            target: null
            minimumPointCount: 1
            maximumPointCount: 1
            onTranslationChanged: (delta) => {
                let shift = -delta.x / interaction.width * (chart.viewEnd - chart.viewStart)
                chart.setView(chart.viewStart + shift, chart.viewEnd + shift)
            }
        }
        PinchHandler {
            target: null
            onScaleChanged: (delta) => chart.zoom(delta, Math.max(0, Math.min(1, centroid.position.x / interaction.width)))
        }
        WheelHandler {
            target: null
            onWheel: (event) => {
                chart.zoom(event.angleDelta.y > 0 ? 1.2 : 1/1.2, event.x / interaction.width)
                event.accepted = true
            }
        }
    }
    Text {
        anchors.centerIn: parent
        visible: !chart.info.loaded
        text: "Abra um arquivo do equipamento"
        color: "#698296"; font.pixelSize: 16
        width: parent.width - 36; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter
    }
}
