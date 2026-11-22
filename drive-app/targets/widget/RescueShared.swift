// Shared model + palette for the Rescue widget and Live Activity (widget extension target).
//
// Data hand-off app -> widget uses a SHARED KEYCHAIN ACCESS GROUP, not an App Group: EAS cannot create/link App Group
// identifiers when signing with an App Store Connect API key, whereas every provisioning profile already allows
// "<TeamID>.*" keychain groups. The app (modules/rescue-engagement) writes one JSON item; the widget reads it.
// Keep RescueKeychain + RescueActivityAttributes byte-for-byte in sync with
// modules/rescue-engagement/ios/RescueEngagementModule.swift.
import SwiftUI
import ActivityKit
import Security

enum RescuePalette {
    static let paper = Color(red: 0.957, green: 0.969, blue: 0.965)   // #F4F7F6
    static let ink = Color(red: 0.055, green: 0.106, blue: 0.149)     // #0E1B26
    static let ink2 = Color(red: 0.267, green: 0.325, blue: 0.373)    // #44535F
    static let ink3 = Color(red: 0.435, green: 0.494, blue: 0.541)    // #6F7E8A
    static let accent = Color(red: 0.055, green: 0.792, blue: 0.627)  // #0ECAA0
    static let accentOn = Color(red: 0.024, green: 0.165, blue: 0.133) // #062A22
}

enum RescueKeychain {
    static let accessGroup = "A5X77AGYX4.so.bolls.fuelback.shared"
    static let service = "so.bolls.fuelback.shared"
    static let account = "widget"

    static func read() -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecAttrAccessGroup as String: accessGroup,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var out: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &out)
        guard status == errSecSuccess else { return nil }
        return out as? Data
    }
}

/// What the home-screen widget shows. Written by the app via setWidgetData(). All values come from the app's
/// demo/replay rescue set — never live MILES data — and the widget says so ("Demo").
struct RescueSnapshot: Codable {
    var nearbyCount: Double
    var bestRewardEur: Double
    var bestWalkMin: Double
    var updatedAt: Double // ms since epoch
    var bestVehicleId: String?

    var count: Int { max(0, Int(nearbyCount.rounded())) }
    var reward: Int { Int(bestRewardEur.rounded()) }
    var walk: Int { max(1, Int(bestWalkMin.rounded())) }
    var updated: Date { Date(timeIntervalSince1970: updatedAt / 1000) }

    var tapURL: URL {
        if let id = bestVehicleId, !id.isEmpty, let u = URL(string: "fuelback://rescue/\(id)") { return u }
        return URL(string: "fuelback://")!
    }

    static let sample = RescueSnapshot(nearbyCount: 3, bestRewardEur: 5, bestWalkMin: 4,
                                       updatedAt: Date().timeIntervalSince1970 * 1000, bestVehicleId: nil)

    /// nil when the app has never written data (widget then asks you to open the app instead of inventing numbers).
    static func load() -> RescueSnapshot? {
        guard let data = RescueKeychain.read() else { return nil }
        return try? JSONDecoder().decode(RescueSnapshot.self, from: data)
    }
}

/// Live Activity attributes. MUST stay identical (name + fields) to the copy in the app's native module.
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
