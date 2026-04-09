// SocketServer.swift — Component BT-001.2
//
// Unix domain socket server that bridges osm-bt (Swift) with osm-core (Python).
// Listens on /tmp/osmphone.sock. Accepts ONE client at a time (osm-core).
//
// Architecture:
//   - Uses low-level POSIX sockets (not Network.framework) for Unix domain support
//   - GCD DispatchSource for non-blocking async I/O on the RunLoop
//   - JSON-over-newline framing: reads into a buffer, splits on 0x0A boundaries
//   - Delegates parsed commands to AppCoordinator via SocketServerDelegate
//
// Threading: Socket I/O runs on a private serial DispatchQueue.
// Delegate callbacks are dispatched to the main thread (for IOBluetooth safety).
//
// Known issue: Only supports one client. If osm-core reconnects, the old
// connection is dropped silently. This is intentional — only one orchestrator.

import Foundation

/// Delegate for receiving parsed commands from connected clients.
protocol SocketServerDelegate: AnyObject {
    func socketServer(_ server: SocketServer, didReceiveCommand id: String, type: CommandType, payload: [String: Any])
    func socketServerClientConnected(_ server: SocketServer)
    func socketServerClientDisconnected(_ server: SocketServer)
}

/// Unix domain socket server using JSON-over-newline protocol.
/// Accepts one client (osm-core Python backend) at a time.
class SocketServer {
    let socketPath: String
    weak var delegate: SocketServerDelegate?

    private var serverSocket: Int32 = -1
    private var clientSocket: Int32 = -1
    private var clientSource: DispatchSourceRead?
    private var serverSource: DispatchSourceRead?
    private var readBuffer = Data()
    private let queue = DispatchQueue(label: "com.osmphone.socket", qos: .userInteractive)

    init(socketPath: String = "/tmp/osmphone.sock") {
        self.socketPath = socketPath
    }

    // MARK: - Lifecycle

    func start() throws {
        // Remove stale socket file
        unlink(socketPath)

        // Create Unix domain socket
        serverSocket = socket(AF_UNIX, SOCK_STREAM, 0)
        guard serverSocket >= 0 else {
            throw SocketError.createFailed(errno)
        }

        // Bind
        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let pathBytes = socketPath.utf8CString
        let maxLen = MemoryLayout.size(ofValue: addr.sun_path)
        precondition(pathBytes.count <= maxLen, "Socket path too long")
        withUnsafeMutableBytes(of: &addr.sun_path) { buf in
            for (i, byte) in pathBytes.prefix(maxLen).enumerated() {
                buf[i] = UInt8(bitPattern: byte)
            }
        }

        let bindResult = withUnsafePointer(to: &addr) { addrPtr in
            addrPtr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockaddrPtr in
                bind(serverSocket, sockaddrPtr, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard bindResult == 0 else {
            close(serverSocket)
            throw SocketError.bindFailed(errno)
        }

        // Listen
        guard listen(serverSocket, 1) == 0 else {
            close(serverSocket)
            throw SocketError.listenFailed(errno)
        }

        // Accept connections asynchronously
        serverSource = DispatchSource.makeReadSource(fileDescriptor: serverSocket, queue: queue)
        serverSource?.setEventHandler { [weak self] in
            self?.acceptClient()
        }
        serverSource?.resume()

        print("[SocketServer] Listening on \(socketPath)")
    }

    func stop() {
        serverSource?.cancel()
        serverSource = nil
        clientSource?.cancel()
        clientSource = nil
        if clientSocket >= 0 { close(clientSocket); clientSocket = -1 }
        if serverSocket >= 0 { close(serverSocket); serverSocket = -1 }
        unlink(socketPath)
        print("[SocketServer] Stopped")
    }

    // MARK: - Send Event

    func sendEvent(_ data: Data) {
        guard clientSocket >= 0 else { return }
        queue.async { [weak self] in
            guard let self = self, self.clientSocket >= 0 else { return }
            data.withUnsafeBytes { buf in
                if let ptr = buf.baseAddress {
                    _ = Darwin.write(self.clientSocket, ptr, data.count)
                }
            }
        }
    }

    var isClientConnected: Bool {
        return clientSocket >= 0
    }

    // MARK: - Private

    private func acceptClient() {
        var addr = sockaddr_un()
        var len = socklen_t(MemoryLayout<sockaddr_un>.size)
        let fd = withUnsafeMutablePointer(to: &addr) { addrPtr in
            addrPtr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockaddrPtr in
                accept(serverSocket, sockaddrPtr, &len)
            }
        }
        guard fd >= 0 else { return }

        // Disconnect existing client
        if clientSocket >= 0 {
            clientSource?.cancel()
            close(clientSocket)
        }

        clientSocket = fd
        readBuffer = Data()
        print("[SocketServer] Client connected (fd=\(fd))")

        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.delegate?.socketServerClientConnected(self)
        }

        // Read from client
        clientSource = DispatchSource.makeReadSource(fileDescriptor: fd, queue: queue)
        clientSource?.setEventHandler { [weak self] in
            self?.readFromClient()
        }
        clientSource?.setCancelHandler { [weak self] in
            guard let self = self else { return }
            if self.clientSocket == fd {
                close(fd)
                self.clientSocket = -1
                DispatchQueue.main.async {
                    self.delegate?.socketServerClientDisconnected(self)
                }
                print("[SocketServer] Client disconnected")
            }
        }
        clientSource?.resume()
    }

    private func readFromClient() {
        var buf = [UInt8](repeating: 0, count: 65536)
        let n = read(clientSocket, &buf, buf.count)
        if n <= 0 {
            clientSource?.cancel()
            return
        }

        readBuffer.append(contentsOf: buf[0..<n])

        // Parse complete lines (newline-delimited JSON)
        while let newlineIndex = readBuffer.firstIndex(of: 0x0A) {
            let lineData = readBuffer[readBuffer.startIndex..<newlineIndex]
            readBuffer = Data(readBuffer[readBuffer.index(after: newlineIndex)...])

            guard !lineData.isEmpty else { continue }

            do {
                let (id, type, payload) = try CommandParser.parse(Data(lineData))
                DispatchQueue.main.async { [weak self] in
                    guard let self = self else { return }
                    self.delegate?.socketServer(self, didReceiveCommand: id, type: type, payload: payload)
                }
            } catch {
                print("[SocketServer] Parse error: \(error)")
            }
        }
    }
}

// MARK: - Errors

enum SocketError: Error, CustomStringConvertible {
    case createFailed(Int32)
    case bindFailed(Int32)
    case listenFailed(Int32)

    var description: String {
        switch self {
        case .createFailed(let e): return "Socket create failed: \(String(cString: strerror(e)))"
        case .bindFailed(let e): return "Socket bind failed: \(String(cString: strerror(e)))"
        case .listenFailed(let e): return "Socket listen failed: \(String(cString: strerror(e)))"
        }
    }
}
