// Entry point for the widget extension: the home-screen widget + the Live Activity.
import WidgetKit
import SwiftUI

@main
struct RescueWidgetBundle: WidgetBundle {
    var body: some Widget {
        RescueWidget()
        RescueLiveActivity()
    }
}
