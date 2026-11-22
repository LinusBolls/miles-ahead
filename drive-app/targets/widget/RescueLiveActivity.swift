// Live Activity: rescue progress on the Lock Screen and in the Dynamic Island.
// walk to the car -> drive it to the destination -> done (credit). Started/updated by the app via
// modules/rescue-engagement (ActivityKit has no built-in Expo JS API). This file is the UI only.
import ActivityKit
import WidgetKit
import SwiftUI

private enum Stage: String {
    case walking, driving, done
    init(_ raw: String) { self = Stage(rawValue: raw) ?? .walking }
    var index: Int { self == .walking ? 0 : (self == .driving ? 1 : 2) }
    var symbol: String { self == .walking ? "figure.walk" : (self == .driving ? "car.fill" : "checkmark.circle.fill") }
}

private func headline(_ a: RescueActivityAttributes, _ s: RescueActivityAttributes.ContentState) -> String {
    switch Stage(s.stage) {
    case .walking: return "Walk to the \(a.carModel)"
    case .driving: return "Drive to \(a.destinationName)"
    case .done: return "Rescued · €\(a.rewardEur) credited"
    }
}

private func detail(_ a: RescueActivityAttributes, _ s: RescueActivityAttributes.ContentState) -> String {
    switch Stage(s.stage) {
    case .walking: return "\(s.minutesLeft) min walk left · \(a.plate)"
    case .driving: return "\(s.minutesLeft) min drive left · \(a.plate)"
    case .done: return "Thanks for moving \(a.plate)"
    }
}

private struct StepBar: View {
    let stage: Stage
    var dark: Bool = false
    var body: some View {
        HStack(spacing: 6) {
            step(0, "Walk")
            step(1, "Drive")
            step(2, "Done")
        }
    }
    func step(_ i: Int, _ label: String) -> some View {
        let reached = stage.index >= i
        let base: Color = dark ? .white : RescuePalette.ink
        return VStack(alignment: .leading, spacing: 3) {
            Capsule()
                .fill(reached ? RescuePalette.accent : base.opacity(0.15))
                .frame(height: 4)
            Text(label)
                .font(.system(size: 11, weight: stage.index == i ? .bold : .medium))
                .foregroundColor(reached ? base : base.opacity(0.45))
        }
        .frame(maxWidth: .infinity)
    }
}

private struct RewardPill: View {
    let eur: Int
    var size: CGFloat = 17
    var body: some View {
        Text("€\(eur)")
            .font(.system(size: size, weight: .heavy, design: .rounded))
            .foregroundColor(RescuePalette.accentOn)
            .padding(.horizontal, 9).padding(.vertical, 3)
            .background(RescuePalette.accent)
            .clipShape(Capsule())
    }
}

struct RescueLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: RescueActivityAttributes.self) { context in
            // Lock Screen / banner
            let a = context.attributes
            let s = context.state
            let stage = Stage(s.stage)
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .center, spacing: 10) {
                    RewardPill(eur: a.rewardEur)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(headline(a, s))
                            .font(.system(size: 15, weight: .bold))
                            .foregroundColor(RescuePalette.ink)
                            .lineLimit(1)
                        Text(detail(a, s))
                            .font(.system(size: 13))
                            .foregroundColor(RescuePalette.ink2)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 0)
                    if stage == .walking {
                        VStack(alignment: .trailing, spacing: 0) {
                            Text("held")
                                .font(.system(size: 10, weight: .medium))
                                .foregroundColor(RescuePalette.ink3)
                            Text(a.expiresAt, style: .timer)
                                .font(.system(size: 14, weight: .semibold).monospacedDigit())
                                .foregroundColor(RescuePalette.ink)
                                .multilineTextAlignment(.trailing)
                                .frame(width: 52, alignment: .trailing)
                        }
                    } else {
                        Image(systemName: stage.symbol)
                            .font(.system(size: 20, weight: .semibold))
                            .foregroundColor(RescuePalette.accent)
                    }
                }
                StepBar(stage: stage)
                HStack {
                    Text("Rescue · concept demo").font(.system(size: 10, weight: .medium))
                    Spacer()
                    Text("to \(a.destinationName)").font(.system(size: 10, weight: .medium)).lineLimit(1)
                }
                .foregroundColor(RescuePalette.ink3)
            }
            .padding(14)
            .activityBackgroundTint(RescuePalette.paper)
            .activitySystemActionForegroundColor(RescuePalette.ink)
        } dynamicIsland: { context in
            let a = context.attributes
            let s = context.state
            let stage = Stage(s.stage)
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    RewardPill(eur: a.rewardEur, size: 16)
                        .padding(.leading, 4)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    if stage == .done {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.system(size: 22)).foregroundColor(RescuePalette.accent)
                            .padding(.trailing, 4)
                    } else {
                        Text("\(s.minutesLeft) min")
                            .font(.system(size: 16, weight: .semibold).monospacedDigit())
                            .foregroundColor(.white)
                            .padding(.trailing, 4)
                    }
                }
                DynamicIslandExpandedRegion(.center) {
                    Text(headline(a, s))
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(.white)
                        .lineLimit(1)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    VStack(alignment: .leading, spacing: 6) {
                        StepBar(stage: stage, dark: true)
                        Text(detail(a, s))
                            .font(.system(size: 12))
                            .foregroundColor(.white.opacity(0.7))
                            .lineLimit(1)
                    }
                    .padding(.horizontal, 4)
                }
            } compactLeading: {
                Text("€\(a.rewardEur)")
                    .font(.system(size: 14, weight: .heavy, design: .rounded))
                    .foregroundColor(RescuePalette.accent)
            } compactTrailing: {
                if stage == .done {
                    Image(systemName: "checkmark.circle.fill").foregroundColor(RescuePalette.accent)
                } else {
                    HStack(spacing: 3) {
                        Image(systemName: stage.symbol).font(.system(size: 12, weight: .semibold))
                        Text("\(s.minutesLeft)m").font(.system(size: 13, weight: .semibold).monospacedDigit())
                    }
                    .foregroundColor(.white)
                }
            } minimal: {
                Image(systemName: stage.symbol)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundColor(RescuePalette.accent)
            }
            .widgetURL(URL(string: "fuelback://"))
            .keylineTint(RescuePalette.accent)
        }
    }
}
