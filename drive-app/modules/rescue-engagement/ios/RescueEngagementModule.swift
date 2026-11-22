// Native bridge for the Rescue engagement surfaces: ActivityKit (Live Activity) start/update/end and the home-screen
// widget's data (shared keychain item + WidgetCenter reload). The UI for both lives in targets/widget/.
import ExpoModulesCore
import ActivityKit
import WidgetKit
import Security

// MUST stay identical (name + fields) to targets/widget/RescueShared.swift — ActivityKit matches them by type name.
struct RescueActivityAttributes: ActivityAttributes {
    public struct ContentState: Codable, Hashable {
        var stage: String // "walking" | "driving" | "done"
        var minutesLeft: Int
    }
    var carModel: String
    var plate: String
    var rewardEur: Int
    var walkMin: Int
    var destinationName: String
    var expiresAt: Date
}

// Shared keychain item the widget reads (see targets/widget/RescueShared.swift for why not an App Group).
enum RescueKeychain {
    static let accessGroup = "A5X77AGYX4.so.bolls.fuelback.shared"
    static let service = "so.bolls.fuelback.shared"
    static let account = "widget"

    static func write(_ data: Data) -> Bool {
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecAttrAccessGroup as String: accessGroup,
        ]
        let attrs: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock,
        ]
        var status = SecItemUpdate(base as CFDictionary, attrs as CFDictionary)
        if status == errSecItemNotFound {
            var add = base
            add.merge(attrs) { _, new in new }
            status = SecItemAdd(add as CFDictionary, nil)
        }
        return status == errSecSuccess
    }
}

public class RescueEngagementModule: Module {
    public func definition() -> ModuleDefinition {
        Name("RescueEngagement")

        Function("areActivitiesEnabled") { () -> Bool in
            return ActivityAuthorizationInfo().areActivitiesEnabled
        }

        // Ends any running rescue activity, then starts a new one. Returns the activity id, or nil when Live Activities
        // are disabled/unsupported (the JS side treats that as a no-op).
        AsyncFunction("startActivity") { (carModel: String, plate: String, rewardEur: Double, walkMin: Double,
                                          destinationName: String, expiresAtMs: Double) async throws -> String? in
            for existing in Activity<RescueActivityAttributes>.activities {
                await existing.end(nil, dismissalPolicy: .immediate)
            }
            guard ActivityAuthorizationInfo().areActivitiesEnabled else { return nil }
            let walk = max(1, Int(walkMin.rounded()))
            let attributes = RescueActivityAttributes(
                carModel: carModel,
                plate: plate,
                rewardEur: Int(rewardEur.rounded()),
                walkMin: walk,
                destinationName: destinationName,
                expiresAt: Date(timeIntervalSince1970: expiresAtMs / 1000)
            )
            let state = RescueActivityAttributes.ContentState(stage: "walking", minutesLeft: walk)
            let activity = try Activity.request(
                attributes: attributes,
                content: ActivityContent(state: state, staleDate: nil),
                pushType: nil
            )
            return activity.id
        }

        AsyncFunction("updateActivity") { (stage: String, minutesLeft: Double) async -> Bool in
            let state = RescueActivityAttributes.ContentState(stage: stage, minutesLeft: max(0, Int(minutesLeft.rounded())))
            var updated = false
            for activity in Activity<RescueActivityAttributes>.activities {
                await activity.update(ActivityContent(state: state, staleDate: nil))
                updated = true
            }
            return updated
        }

        // Ends the activity but leaves its final state (e.g. "Rescued · €5 credited") on the Lock Screen for 2 minutes.
        AsyncFunction("endActivity") { () async -> Void in
            for activity in Activity<RescueActivityAttributes>.activities {
                await activity.end(nil, dismissalPolicy: .after(Date().addingTimeInterval(120)))
            }
        }

        // json = {"nearbyCount","bestRewardEur","bestWalkMin","updatedAt"(ms),"bestVehicleId"?}
        Function("setWidgetData") { (json: String) -> Bool in
            let ok = RescueKeychain.write(Data(json.utf8))
            WidgetCenter.shared.reloadAllTimelines()
            return ok
        }
    }
}
