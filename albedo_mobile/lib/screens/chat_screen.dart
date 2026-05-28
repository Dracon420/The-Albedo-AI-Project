import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:speech_to_text/speech_to_text.dart';
import 'package:uuid/uuid.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../theme.dart';

// ── Notification plugin (init once) ──────────────────────────────────────────
final _notifs = FlutterLocalNotificationsPlugin();
bool _notifsReady = false;

Future<void> _initNotifs() async {
  if (_notifsReady) return;
  const android = AndroidInitializationSettings('@mipmap/ic_launcher');
  await _notifs.initialize(const InitializationSettings(android: android));
  _notifsReady = true;
}

Future<void> _showNotification(String title, String body) async {
  await _initNotifs();
  const details = NotificationDetails(
    android: AndroidNotificationDetails(
      'albedo_alerts', 'Albedo Alerts',
      channelDescription: 'Notifications from Albedo AI',
      importance: Importance.high,
      priority: Priority.high,
    ),
  );
  await _notifs.show(DateTime.now().millisecondsSinceEpoch & 0x7fffffff, title, body, details);
}

// ── Message model ─────────────────────────────────────────────────────────────
enum _Sender { user, albedo, system }

class _Msg {
  final String text;
  final _Sender sender;
  final DateTime time;
  const _Msg({required this.text, required this.sender, required this.time});
}

// ── Chat screen ───────────────────────────────────────────────────────────────
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> with WidgetsBindingObserver {
  // WebSocket
  WebSocketChannel? _channel;
  StreamSubscription? _sub;
  bool _wsConnected  = false;
  bool _albedoOnline = false;
  Timer? _reconnTimer;
  String _relayUrl = '';
  String _token    = '';

  // Messages
  final List<_Msg> _msgs  = [];
  final _scroll = ScrollController();

  // Text input
  final _textCtrl = TextEditingController();
  bool _sending = false;

  // Speech
  final _stt     = SpeechToText();
  bool _sttReady = false;
  bool _listening = false;

  // Pending reply IDs (so we know to show "typing…")
  final Set<String> _pending = {};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _initSpeech();
    _initNotifs();
    _loadAndConnect();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _reconnTimer?.cancel();
    _sub?.cancel();
    _channel?.sink.close();
    _textCtrl.dispose();
    _scroll.dispose();
    super.dispose();
  }

  // ── Load creds and connect ──────────────────────────────────────────────────
  Future<void> _loadAndConnect() async {
    final prefs = await SharedPreferences.getInstance();
    _relayUrl = prefs.getString('relay_url') ?? '';
    _token    = prefs.getString('token')     ?? '';
    if (_relayUrl.isEmpty || _token.isEmpty) {
      if (mounted) Navigator.pushReplacementNamed(context, '/setup');
      return;
    }
    _connect();
  }

  // ── WebSocket ───────────────────────────────────────────────────────────────
  void _connect() {
    _sub?.cancel();
    _channel?.sink.close();

    final uri = Uri.parse('$_relayUrl/phone/$_token');
    try {
      _channel = WebSocketChannel.connect(uri);
      _sub = _channel!.stream.listen(
        _onData,
        onError: (_) => _onDisconnect(),
        onDone:  ()  => _onDisconnect(),
        cancelOnError: false,
      );
      setState(() { _wsConnected = true; });
      _addSystem('Connected to relay.');
    } catch (e) {
      _onDisconnect();
    }
  }

  void _onDisconnect() {
    if (!mounted) return;
    setState(() { _wsConnected = false; _albedoOnline = false; });
    _reconnTimer?.cancel();
    _reconnTimer = Timer(const Duration(seconds: 5), () {
      if (mounted) _connect();
    });
  }

  void _onData(dynamic raw) {
    Map<String, dynamic> msg;
    try { msg = jsonDecode(raw as String) as Map<String, dynamic>; }
    catch (_) { return; }

    final type = msg['type'] as String? ?? '';
    switch (type) {
      case 'response':
        final id   = msg['id'] as String? ?? '';
        final text = msg['text'] as String? ?? '';
        _pending.remove(id);
        _addMsg(text, _Sender.albedo);
        break;

      case 'status':
        // Albedo sends periodic heartbeats
        final online = msg['online'] as bool? ?? false;
        setState(() { _albedoOnline = online; });
        break;

      case 'push':
        // Unsolicited alert from Albedo
        final text = msg['text'] as String? ?? 'Alert from Albedo';
        _addMsg(text, _Sender.albedo);
        _showNotification('Albedo', text);
        break;
    }
  }

  // ── Send message ─────────────────────────────────────────────────────────────
  Future<void> _sendText(String text) async {
    text = text.trim();
    if (text.isEmpty || !_wsConnected) return;
    setState(() { _sending = true; });
    _addMsg(text, _Sender.user);

    final id = const Uuid().v4();
    _pending.add(id);
    try {
      _channel?.sink.add(jsonEncode({'type': 'query', 'text': text, 'id': id}));
    } catch (_) { _pending.remove(id); }

    _textCtrl.clear();
    setState(() { _sending = false; });
  }

  // ── Speech ────────────────────────────────────────────────────────────────────
  Future<void> _initSpeech() async {
    _sttReady = await _stt.initialize(
      onError: (_) => setState(() { _listening = false; }),
      onStatus: (s) {
        if (s == 'done' || s == 'notListening') setState(() { _listening = false; });
      },
    );
    setState(() {});
  }

  Future<void> _toggleMic() async {
    if (!_sttReady) return;
    if (_listening) {
      await _stt.stop();
      setState(() { _listening = false; });
    } else {
      setState(() { _listening = true; });
      await _stt.listen(
        onResult: (r) {
          if (r.finalResult) {
            _sendText(r.recognizedWords);
            setState(() { _listening = false; });
          }
        },
        listenFor: const Duration(seconds: 30),
        pauseFor:  const Duration(seconds: 3),
        localeId:  'en_US',
      );
    }
  }

  // ── Helpers ────────────────────────────────────────────────────────────────
  void _addMsg(String text, _Sender sender) {
    if (!mounted) return;
    setState(() { _msgs.add(_Msg(text: text, sender: sender, time: DateTime.now())); });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(
          _scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _addSystem(String text) => _addMsg(text, _Sender.system);

  Future<void> _unpair() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: kBgCard,
        title: const Text('UNPAIR DEVICE', style: TextStyle(color: kCyan, letterSpacing: 1.5)),
        content: const Text(
          'Remove pairing? You will need to scan the QR code again.',
          style: TextStyle(color: kTextPrim),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('CANCEL', style: TextStyle(color: kTextDim)),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('UNPAIR', style: TextStyle(color: kRed)),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('relay_url');
    await prefs.remove('token');
    if (mounted) Navigator.pushReplacementNamed(context, '/setup');
  }

  // ── Build ─────────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: kBgDark,
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('ALBEDO AI'),
            Text(
              _wsConnected
                  ? (_albedoOnline ? '● ONLINE' : '◌ RELAY CONNECTED')
                  : '✕ DISCONNECTED',
              style: TextStyle(
                fontSize: 10,
                letterSpacing: 1,
                color: _wsConnected
                    ? (_albedoOnline ? kGreen : kAmber)
                    : kRed,
                fontWeight: FontWeight.normal,
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.link_off, size: 18),
            tooltip: 'Unpair',
            onPressed: _unpair,
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(child: _buildMessageList()),
          _buildTypingBar(),
          _buildInputBar(),
        ],
      ),
    );
  }

  // ── Message list ──────────────────────────────────────────────────────────────
  Widget _buildMessageList() {
    if (_msgs.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.radio, size: 48, color: kCyanDim),
            const SizedBox(height: 16),
            const Text('ALBEDO MOBILE', style: TextStyle(color: kCyan, letterSpacing: 3)),
            const SizedBox(height: 8),
            Text(
              _wsConnected ? 'Send a message or speak.' : 'Connecting to relay...',
              style: const TextStyle(color: kTextDim, fontSize: 12),
            ),
          ],
        ),
      );
    }
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.symmetric(vertical: 8),
      itemCount: _msgs.length,
      itemBuilder: (_, i) => _buildBubble(_msgs[i]),
    );
  }

  Widget _buildBubble(_Msg msg) {
    if (msg.sender == _Sender.system) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 12),
        child: Center(
          child: Text(
            msg.text,
            style: const TextStyle(color: kTextDim, fontSize: 11, letterSpacing: 0.5),
          ),
        ),
      );
    }

    final isUser = msg.sender == _Sender.user;
    return Padding(
      padding: EdgeInsets.only(
        left: isUser ? 48 : 12,
        right: isUser ? 12 : 48,
        top: 4,
        bottom: 4,
      ),
      child: Align(
        alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: isUser ? kCyanDim : kBgCard,
            border: Border.all(
              color: isUser ? kCyan.withAlpha(80) : kBorder,
            ),
            borderRadius: BorderRadius.only(
              topLeft:     const Radius.circular(12),
              topRight:    const Radius.circular(12),
              bottomLeft:  Radius.circular(isUser ? 12 : 2),
              bottomRight: Radius.circular(isUser ? 2  : 12),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (!isUser)
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text(
                    'ALBEDO',
                    style: TextStyle(
                      color: kCyan.withAlpha(180),
                      fontSize: 9,
                      letterSpacing: 2,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              SelectableText(
                msg.text,
                style: TextStyle(
                  color: isUser ? kCyan : kTextPrim,
                  fontSize: 14,
                  height: 1.45,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  // ── Typing indicator ──────────────────────────────────────────────────────────
  Widget _buildTypingBar() {
    if (_pending.isEmpty) return const SizedBox.shrink();
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      color: kBgCard,
      child: Row(
        children: [
          SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(
              strokeWidth: 1.5,
              color: kCyan.withAlpha(160),
            ),
          ),
          const SizedBox(width: 10),
          const Text(
            'Albedo is thinking…',
            style: TextStyle(color: kTextDim, fontSize: 12, fontStyle: FontStyle.italic),
          ),
        ],
      ),
    );
  }

  // ── Input bar ─────────────────────────────────────────────────────────────────
  Widget _buildInputBar() {
    final canSend = _wsConnected && !_sending;
    return Container(
      padding: const EdgeInsets.fromLTRB(8, 8, 8, 12),
      decoration: const BoxDecoration(
        color: kBgCard,
        border: Border(top: BorderSide(color: kBorder)),
      ),
      child: SafeArea(
        top: false,
        child: Row(
          children: [
            // Mic button
            GestureDetector(
              onTap: _sttReady ? _toggleMic : null,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: _listening ? kCyan.withAlpha(40) : Colors.transparent,
                  border: Border.all(
                    color: _listening ? kCyan : kBorder,
                    width: _listening ? 2 : 1,
                  ),
                ),
                child: Icon(
                  _listening ? Icons.mic : Icons.mic_none,
                  color: _listening ? kCyan : kTextDim,
                  size: 20,
                ),
              ),
            ),
            const SizedBox(width: 8),

            // Text field
            Expanded(
              child: TextField(
                controller: _textCtrl,
                style: const TextStyle(color: kTextPrim, fontSize: 14),
                decoration: InputDecoration(
                  hintText: _listening ? 'Listening…' : 'Message Albedo…',
                  contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                ),
                keyboardType: TextInputType.multiline,
                minLines: 1,
                maxLines: 4,
                textInputAction: TextInputAction.send,
                onSubmitted: canSend ? _sendText : null,
                enabled: !_listening,
              ),
            ),
            const SizedBox(width: 8),

            // Send button
            GestureDetector(
              onTap: canSend
                  ? () => _sendText(_textCtrl.text)
                  : null,
              child: Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: canSend ? kCyanDim : kBgCard,
                  borderRadius: BorderRadius.circular(4),
                  border: Border.all(
                    color: canSend ? kCyan : kBorder,
                  ),
                ),
                child: Icon(
                  Icons.send,
                  color: canSend ? kCyan : kTextDim,
                  size: 18,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
