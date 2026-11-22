// Home-screen + Lock Screen widget: "N cars to rescue near you · best €5 · 4 min walk".
// Reads the snapshot the app wrote (shared keychain group, see RescueShared.swift). Tap opens the best car's rescue card.
import WidgetKit
import SwiftUI

struct RescueEntry: TimelineEntry {
    let date: Date
    let snapshot: RescueSnapshot?
}

struct RescueProvider: TimelineProvider {
    func placeholder(in context: Context) -> RescueEntry { RescueEntry(date: Date(), snapshot: .sample) }

    func getSnapshot(in context: Context, completion: @escaping (RescueEntry) -> Void) {
        // Widget gallery preview: show the sample layout if the app hasn't written anything yet.
        let snap = RescueSnapshot.load() ?? (context.isPreview ? .sample : nil)
        completion(RescueEntry(date: Date(), snapshot: snap))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<RescueEntry>) -> Void) {
        let entry = RescueEntry(date: Date(), snapshot: RescueSnapshot.load())
        // The app calls WidgetCenter.reloadAllTimelines() whenever it has fresh data; this is just a safety refresh.
        completion(Timeline(entries: [entry], policy: .after(Date().addingTimeInterval(15 * 60))))
    }
}

struct RescueWidgetView: View {
    @Environment(\.widgetFamily) var family
    var entry: RescueEntry

    var body: some View {
        content
            .widgetURL(entry.snapshot?.tapURL ?? URL(string: "fuelback://")!)
            .containerBackground(for: .widget) {
                if family == .accessoryRectangular { Color.clear } else { RescuePalette.paper }
            }
    }

    @ViewBuilder var content: some View {
        if family == .accessoryRectangular {
            lockScreen
        } else if let s = entry.snapshot {
            home(s)
        } else {
            empty
        }
    }

    // Lock Screen (accessoryRectangular): system-tinted, no colors.
    @ViewBuilder var lockScreen: some View {
        if let s = entry.snapshot, s.count > 0 {
            VStack(alignment: .leading, spacing: 1) {
                Label("\(s.count) to rescue nearby", systemImage: "car.fill")
                    .font(.system(size: 14, weight: .semibold))
                Text("Best €\(s.reward) · \(s.walk) min walk")
                    .font(.system(size: 13))
                Text("Demo data").font(.system(size: 11)).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            VStack(alignment: .leading, spacing: 1) {
                Label("Rescue", systemImage: "car.fill").font(.system(size: 14, weight: .semibold))
                Text(entry.snapshot == nil ? "Open the app to load" : "Nothing nearby now")
                    .font(.system(size: 13)).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    func home(_ s: RescueSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Spacer(minLength: 4)
            if s.count > 0 {
                Text("\(s.count)")
                    .font(.system(size: family == .systemSmall ? 38 : 48, weight: .heavy, design: .rounded))
                    .foregroundColor(RescuePalette.ink)
                    .contentTransition(.numericText())
                Text(s.count == 1 ? "car to rescue near you" : "cars to rescue near you")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundColor(RescuePalette.ink)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 4)
                HStack(spacing: 6) {
                    Text("€\(s.reward)")
                        .font(.system(size: 13, weight: .heavy, design: .rounded))
                        .foregroundColor(RescuePalette.accentOn)
                        .padding(.horizontal, 7).padding(.vertical, 2)
                        .background(RescuePalette.accent)
                        .clipShape(Capsule())
                    Text("\(s.walk) min walk")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundColor(RescuePalette.ink2)
                        .lineLimit(1)
                }
            } else {
                Text("No rescues near you right now")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundColor(RescuePalette.ink)
                Spacer(minLength: 4)
                Text("We only ask when a car is about to strand.")
                    .font(.system(size: 12)).foregroundColor(RescuePalette.ink2)
            }
            Spacer(minLength: 4)
            Text("Demo data · \(s.updated, style: .time)")
                .font(.system(size: 10, weight: .medium))
                .foregroundColor(RescuePalette.ink3)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    var header: some View {
        HStack(spacing: 5) {
            Image(systemName: "car.fill").font(.system(size: 11, weight: .bold)).foregroundColor(RescuePalette.accent)
            Text("RESCUE").font(.system(size: 11, weight: .heavy)).foregroundColor(RescuePalette.ink2).kerning(0.6)
            Spacer(minLength: 0)
        }
    }

    var empty: some View {
        VStack(alignment: .leading, spacing: 6) {
            header
            Spacer(minLength: 0)
            Text("Open the app to see cars to rescue near you")
                .font(.system(size: 14, weight: .semibold))
                .foregroundColor(RescuePalette.ink)
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

struct RescueWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "RescueWidget", provider: RescueProvider()) { entry in
            RescueWidgetView(entry: entry)
        }
        .configurationDisplayName("Rescue nearby")
        .description("Cars near you that pay ride credit to move.")
        .supportedFamilies([.systemSmall, .systemMedium, .accessoryRectangular])
    }
}
