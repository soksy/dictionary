import Toybox.Activity;
import Toybox.ActivityMonitor;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.Time;
import Toybox.Time.Gregorian;
import Toybox.WatchUi;

//! A simple digital watch face for the Fenix E: big centered time, the date
//! below it, battery percentage at the top, and step count at the bottom.
//!
//! Everything is positioned relative to dc.getWidth()/getHeight(), so the same
//! code centers correctly on the Fenix E's round 416x416 screen and on any
//! other device you add to the products list — no hard-coded pixel offsets.
class SimpleFaceView extends WatchUi.WatchFace {

    private var _isSleeping as Boolean = false;

    function initialize() {
        WatchFace.initialize();
    }

    //! Called once when the layout is loaded. Nothing to precompute here —
    //! we draw everything relative to the current dc in onUpdate().
    function onLayout(dc as Graphics.Dc) as Void {
    }

    function onShow() as Void {
    }

    //! Called by the system to redraw the face — roughly once per minute while
    //! in low-power (sleep) mode, and more often when the watch is awake.
    function onUpdate(dc as Graphics.Dc) as Void {
        var width = dc.getWidth();
        var height = dc.getHeight();
        var centerX = width / 2;
        var centerY = height / 2;

        // Paint the background black (easy on an AMOLED panel and its battery).
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        drawTime(dc, centerX, centerY);
        drawDate(dc, centerX, centerY + (height * 0.22).toNumber());
        drawBattery(dc, centerX, (height * 0.16).toNumber());

        // Steps are the least critical line; skip them in sleep mode to keep
        // the low-power redraw cheap.
        if (!_isSleeping) {
            drawSteps(dc, centerX, height - (height * 0.20).toNumber());
        }
    }

    //! Big centered HH:MM, honouring the watch's 12/24-hour setting.
    private function drawTime(dc as Graphics.Dc, x as Number, y as Number) as Void {
        var clockTime = System.getClockTime();
        var hour = clockTime.hour;

        if (!System.getDeviceSettings().is24Hour) {
            hour = hour % 12;
            if (hour == 0) {
                hour = 12;
            }
        }

        var timeString = Lang.format("$1$:$2$", [
            hour.format("%02d"),
            clockTime.min.format("%02d")
        ]);

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(
            x, y,
            Graphics.FONT_NUMBER_THAI_HOT,
            timeString,
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER
        );
    }

    //! "Thu, Jul 24" style date line below the time.
    private function drawDate(dc as Graphics.Dc, x as Number, y as Number) as Void {
        var info = Gregorian.info(Time.now(), Time.FORMAT_MEDIUM);
        var dateString = Lang.format("$1$, $2$ $3$", [
            info.day_of_week,
            info.month,
            info.day.format("%d")
        ]);

        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(
            x, y,
            Graphics.FONT_SMALL,
            dateString,
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER
        );
    }

    //! Battery percentage near the top of the screen.
    private function drawBattery(dc as Graphics.Dc, x as Number, y as Number) as Void {
        var battery = System.getSystemStats().battery; // 0.0 - 100.0
        var batteryString = battery.format("%d") + "%";

        // Green normally, red when it gets low.
        var color = battery <= 15.0 ? Graphics.COLOR_RED : Graphics.COLOR_GREEN;
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.drawText(
            x, y,
            Graphics.FONT_TINY,
            batteryString,
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER
        );
    }

    //! Today's step count near the bottom of the screen.
    private function drawSteps(dc as Graphics.Dc, x as Number, y as Number) as Void {
        var steps = 0;
        var info = ActivityMonitor.getInfo();
        if (info.steps != null) {
            steps = info.steps;
        }

        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(
            x, y,
            Graphics.FONT_TINY,
            steps.toString() + " steps",
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER
        );
    }

    //! The device is entering low-power mode (wrist down). Redraws now happen
    //! about once a minute, so we drop the busier elements in onUpdate().
    function onEnterSleep() as Void {
        _isSleeping = true;
        WatchUi.requestUpdate();
    }

    //! The device is leaving low-power mode (wrist raised).
    function onExitSleep() as Void {
        _isSleeping = false;
        WatchUi.requestUpdate();
    }
}
