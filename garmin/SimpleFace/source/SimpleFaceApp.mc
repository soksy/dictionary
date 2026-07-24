import Toybox.Application;
import Toybox.Lang;
import Toybox.WatchUi;

//! Application entry point. For a watch face this is minimal: it just hands
//! the system our single WatchFace view.
class SimpleFaceApp extends Application.AppBase {

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state as Dictionary?) as Void {
    }

    function onStop(state as Dictionary?) as Void {
    }

    //! Return the initial view. The system shows this whenever the watch face
    //! is active.
    function getInitialView() as [WatchUi.Views] or [WatchUi.Views, WatchUi.InputDelegates] {
        return [ new SimpleFaceView() ];
    }
}
