// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "osm-bt",
    platforms: [
        .macOS(.v13)
    ],
    targets: [
        .executableTarget(
            name: "OsmBT",
            dependencies: [],
            path: "Sources/OsmBT",
            linkerSettings: [
                .linkedFramework("IOBluetooth"),
                .linkedFramework("CoreBluetooth"),
                .linkedFramework("CoreAudio"),
                .linkedFramework("Foundation")
            ]
        ),
        .testTarget(
            name: "OsmBTTests",
            dependencies: ["OsmBT"],
            path: "Tests/OsmBTTests"
        )
    ]
)
