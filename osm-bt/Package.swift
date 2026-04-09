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
            exclude: ["Info.plist"],
            linkerSettings: [
                .linkedFramework("IOBluetooth"),
                .linkedFramework("CoreBluetooth"),
                .linkedFramework("CoreAudio"),
                .linkedFramework("Foundation"),
                .unsafeFlags(["-Xlinker", "-sectcreate", "-Xlinker", "__TEXT", "-Xlinker", "__info_plist", "-Xlinker", "Sources/OsmBT/Info.plist"])
            ]
        ),
        .testTarget(
            name: "OsmBTTests",
            dependencies: ["OsmBT"],
            path: "Tests/OsmBTTests"
        )
    ]
)
