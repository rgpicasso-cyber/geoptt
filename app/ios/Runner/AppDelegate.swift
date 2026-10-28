import Flutter
import UIKit
import PushToTalk

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate, PTChannelManagerDelegate {

  // MARK: - Constants
  private let methodChannelName = "geoptt/background"
  private let eventChannelName = "geoptt/background/events"

  // MARK: - Properties
  private var channelManager: PTChannelManager!
  private var methodChannel: FlutterMethodChannel!
  private var eventChannel: FlutterEventChannel!
  private var eventSink: FlutterEventSink?
  private var currentChannelUUID: UUID?
  private var pendingJoinCompletion: ((Bool, Error?) -> Void)?

  // MARK: - App Lifecycle

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    // Configurar PushToTalk framework
    setupPushToTalk()

    // Registrar canais de comunicação com Dart
    setupMethodChannel()
    setupEventChannel()

    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
  }

  // MARK: - PushToTalk Setup

  private func setupPushToTalk() {
    // PTChannelManager é o ponto de entrada do framework PushToTalk
    channelManager = PTChannelManager()
    channelManager.delegate = self
  }

  // MARK: - MethodChannel (Dart -> iOS)

  private func setupMethodChannel() {
    guard let controller = window?.rootViewController as? FlutterViewController else { return }

    methodChannel = FlutterMethodChannel(
      name: methodChannelName,
      binaryMessenger: controller.binaryMessenger
    )

    methodChannel.setMethodCallHandler { [weak self] call, result in
      self?.handleMethodCall(call, result: result)
    }
  }

  private func handleMethodCall(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
    switch call.method {
    case "joinChannel":
      guard let args = call.arguments as? [String: Any],
            let channelIdString = args["channelId"] as? String,
            let channelUUID = UUID(uuidString: channelIdString) else {
        result(FlutterError(code: "INVALID_ARGUMENT", message: "channelId (UUID) obrigatório", details: nil))
        return
      }
      joinChannel(channelUUID: channelUUID, result: result)

    case "leaveChannel":
      leaveChannel(result: result)

    case "getStatus":
      let status = getStatus()
      result(status)

    default:
      result(FlutterMethodNotImplemented)
    }
  }

  private func joinChannel(channelUUID: UUID, result: @escaping FlutterResult) {
    // Guardar completion para responder quando o delegate chamar
    pendingJoinCompletion = result

    // Solicitar entrada no canal
    let request = PTChannelJoinRequest(channelUUID: channelUUID)
    channelManager.joinChannel(request)
  }

  private func leaveChannel(result: @escaping FlutterResult) {
    guard let channelUUID = currentChannelUUID else {
      result(FlutterError(code: "NOT_IN_CHANNEL", message: "Não está em nenhum canal", details: nil))
      return
    }

    channelManager.leaveChannel(channelUUID)
    currentChannelUUID = nil
    result(["left": true])
  }

  private func getStatus() -> [String: Any] {
    return [
      "inChannel": currentChannelUUID != nil,
      "channelId": currentChannelUUID?.uuidString ?? NSNull(),
      "platform": "ios",
      "pushToTalkAvailable": true
    ]
  }

  // MARK: - EventChannel (iOS -> Dart)

  private func setupEventChannel() {
    guard let controller = window?.rootViewController as? FlutterViewController else { return }

    eventChannel = FlutterEventChannel(
      name: eventChannelName,
      binaryMessenger: controller.binaryMessenger
    )

    eventChannel.setStreamHandler(self)
  }

  private func emitEvent(_ event: [String: Any]) {
    eventSink?(event)
  }

  // MARK: - PTChannelManagerDelegate

  // Chamado quando o canal é ativado com sucesso (token efêmero recebido)
  func channelManager(_ channelManager: PTChannelManager,
                      didActivate channel: PTChannel,
                      withToken token: Data) {

    currentChannelUUID = channel.channelUUID

    // Converter token para base64 string para enviar ao backend
    let tokenString = token.base64EncodedString()

    emitEvent([
      "event": "channelActivated",
      "channelId": channel.channelUUID.uuidString,
      "ephemeralToken": tokenString
    ])

    // Resolver pending join
    pendingJoinCompletion?(true, nil)
    pendingJoinCompletion = nil
  }

  // Chamado quando falha ao entrar no canal
  func channelManager(_ channelManager: PTChannelManager,
                      didFailToActivate channelUUID: UUID,
                      withError error: Error) {

    emitEvent([
      "event": "channelActivationFailed",
      "channelId": channelUUID.uuidString,
      "error": error.localizedDescription
    ])

    pendingJoinCompletion?(false, error)
    pendingJoinCompletion = nil
  }

  // Chamado quando a transmissão de áudio começa (alguém fala)
  func channelManager(_ channelManager: PTChannelManager,
                      channelUUID: UUID,
                      didBeginTransmittingFrom source: PTChannelTransmitRequestSource) {

    emitEvent([
      "event": "audioTransmissionBegan",
      "channelId": channelUUID.uuidString,
      "source": source.rawValue
    ])
  }

  // Chamado quando a transmissão de áudio termina
  func channelManager(_ channelManager: PTChannelManager,
                      channelUUID: UUID,
                      didEndTransmittingFrom source: PTChannelTransmitRequestSource) {

    emitEvent([
      "event": "audioTransmissionEnded",
      "channelId": channelUUID.uuidString,
      "source": source.rawValue
    ])
  }

  // Chamado quando alguém entra no canal
  func channelManager(_ channelManager: PTChannelManager,
                      channelUUID: UUID,
                      memberDidJoin member: PTChannelMember) {

    emitEvent([
      "event": "memberJoined",
      "channelId": channelUUID.uuidString,
      "memberId": member.userUUID.uuidString,
      "memberName": member.name ?? "Desconhecido"
    ])
  }

  // Chamado quando alguém sai do canal
  func channelManager(_ channelManager: PTChannelManager,
                      channelUUID: UUID,
                      memberDidLeave member: PTChannelMember) {

    emitEvent([
      "event": "memberLeft",
      "channelId": channelUUID.uuidString,
      "memberId": member.userUUID.uuidString
    ])
  }

  // Chamado quando o canal é desativado (saiu ou erro)
  func channelManager(_ channelManager: PTChannelManager,
                      didDeactivate channel: PTChannel) {

    let wasCurrentChannel = (currentChannelUUID == channel.channelUUID)
    currentChannelUUID = nil

    emitEvent([
      "event": "channelDeactivated",
      "channelId": channel.channelUUID.uuidString,
      "wasCurrent": wasCurrentChannel
    ])
  }
}

// MARK: - FlutterStreamHandler (EventChannel)

extension AppDelegate: FlutterStreamHandler {

  func onListen(withArguments arguments: Any?, eventSink events: @escaping FlutterEventSink) -> FlutterError? {
    self.eventSink = events
    return nil
  }

  func onCancel(withArguments arguments: Any?) -> FlutterError? {
    self.eventSink = nil
    return nil
  }
}