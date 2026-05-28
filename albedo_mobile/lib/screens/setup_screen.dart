import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../theme.dart';

class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key});

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  bool _scanning   = true;
  bool _saving     = false;
  String? _error;

  final _relayCtrl = TextEditingController();
  final _tokenCtrl = TextEditingController();
  final _formKey   = GlobalKey<FormState>();

  MobileScannerController? _scanCtrl;

  @override
  void initState() {
    super.initState();
    _scanCtrl = MobileScannerController(
      detectionSpeed: DetectionSpeed.noDuplicates,
      facing: CameraFacing.back,
      torchEnabled: false,
    );
  }

  @override
  void dispose() {
    _scanCtrl?.dispose();
    _relayCtrl.dispose();
    _tokenCtrl.dispose();
    super.dispose();
  }

  // ── QR detected ──────────────────────────────────────────────────────────
  void _onQrDetect(BarcodeCapture capture) {
    final raw = capture.barcodes.firstOrNull?.rawValue;
    if (raw == null || !raw.contains('|')) return;
    _scanCtrl?.stop();
    _parseAndSave(raw);
  }

  // ── Parse "relay_url|token" and persist ──────────────────────────────────
  Future<void> _parseAndSave(String raw) async {
    setState(() { _saving = true; _error = null; });
    try {
      final parts = raw.split('|');
      if (parts.length < 2) throw const FormatException('Invalid QR format.');
      final relayUrl = parts[0].trim();
      final token    = parts[1].trim();
      if (relayUrl.isEmpty || token.isEmpty) {
        throw const FormatException('Relay URL or token is empty.');
      }
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('relay_url', relayUrl);
      await prefs.setString('token', token);
      if (mounted) Navigator.pushReplacementNamed(context, '/chat');
    } catch (e) {
      setState(() {
        _saving = false;
        _error  = e.toString();
        _scanning = false; // fall back to manual entry
      });
    }
  }

  // ── Manual save ──────────────────────────────────────────────────────────
  Future<void> _saveManual() async {
    if (!_formKey.currentState!.validate()) return;
    final raw = '${_relayCtrl.text.trim()}|${_tokenCtrl.text.trim()}';
    await _parseAndSave(raw);
  }

  // ── Build ─────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: kBgDark,
      appBar: AppBar(
        title: const Text('ALBEDO // PAIR DEVICE'),
        actions: [
          TextButton(
            onPressed: () => setState(() { _scanning = !_scanning; _error = null; }),
            child: Text(
              _scanning ? 'MANUAL ENTRY' : 'SCAN QR',
              style: const TextStyle(color: kAmber, fontSize: 11, letterSpacing: 1.2),
            ),
          ),
        ],
      ),
      body: _saving ? _buildSaving() : _scanning ? _buildScanner() : _buildManual(),
    );
  }

  // ── Saving spinner ────────────────────────────────────────────────────────
  Widget _buildSaving() {
    return const Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          CircularProgressIndicator(color: kCyan),
          SizedBox(height: 16),
          Text('PAIRING...', style: TextStyle(color: kCyan, letterSpacing: 2)),
        ],
      ),
    );
  }

  // ── QR Scanner ────────────────────────────────────────────────────────────
  Widget _buildScanner() {
    return Column(
      children: [
        // Instructions banner
        Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
          color: kBgCard,
          child: const Text(
            'Open Albedo Mission Control → MOBILE tab → GENERATE CODE\n'
            'Then scan the QR code below.',
            style: TextStyle(color: kTextDim, fontSize: 12, height: 1.5),
            textAlign: TextAlign.center,
          ),
        ),

        // Camera viewfinder
        Expanded(
          child: Stack(
            children: [
              MobileScanner(
                controller: _scanCtrl!,
                onDetect: _onQrDetect,
              ),
              // Corner overlay
              Center(
                child: Container(
                  width: 220,
                  height: 220,
                  decoration: BoxDecoration(
                    border: Border.all(color: kCyan, width: 2),
                    borderRadius: BorderRadius.circular(8),
                  ),
                ),
              ),
              // Label
              Positioned(
                bottom: 24,
                left: 0,
                right: 0,
                child: Center(
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(
                      color: kBgDark.withAlpha(200),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: const Text(
                      'ALIGN QR CODE WITHIN FRAME',
                      style: TextStyle(color: kCyan, fontSize: 11, letterSpacing: 1.5),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),

        if (_error != null)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            color: kRed.withAlpha(40),
            child: Text(_error!, style: const TextStyle(color: kRed, fontSize: 12)),
          ),
      ],
    );
  }

  // ── Manual entry form ─────────────────────────────────────────────────────
  Widget _buildManual() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Form(
        key: _formKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'MANUAL PAIRING',
              style: TextStyle(color: kCyan, fontSize: 13, letterSpacing: 2, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            const Text(
              'Copy the relay URL and token from Mission Control → MOBILE tab → Copy button.',
              style: TextStyle(color: kTextDim, fontSize: 12, height: 1.5),
            ),
            const SizedBox(height: 24),

            // Relay URL
            const Text('RELAY URL', style: TextStyle(color: kTextDim, fontSize: 11, letterSpacing: 1.5)),
            const SizedBox(height: 6),
            TextFormField(
              controller: _relayCtrl,
              keyboardType: TextInputType.url,
              autocorrect: false,
              style: const TextStyle(color: kTextPrim, fontSize: 13),
              decoration: const InputDecoration(
                hintText: 'wss://albedo-relay.fly.dev/ws',
              ),
              validator: (v) {
                if (v == null || v.trim().isEmpty) return 'Required';
                if (!v.trim().startsWith('wss://') && !v.trim().startsWith('ws://')) {
                  return 'Must start with wss:// or ws://';
                }
                return null;
              },
            ),
            const SizedBox(height: 16),

            // Token
            const Text('TOKEN', style: TextStyle(color: kTextDim, fontSize: 11, letterSpacing: 1.5)),
            const SizedBox(height: 6),
            TextFormField(
              controller: _tokenCtrl,
              autocorrect: false,
              style: const TextStyle(color: kTextPrim, fontSize: 13, letterSpacing: 0.5),
              decoration: const InputDecoration(
                hintText: '32-character hex token',
              ),
              validator: (v) {
                if (v == null || v.trim().isEmpty) return 'Required';
                if (v.trim().length < 8) return 'Token too short';
                return null;
              },
            ),
            const SizedBox(height: 32),

            if (_error != null) ...[
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: kRed.withAlpha(30),
                  border: Border.all(color: kRed.withAlpha(100)),
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Text(_error!, style: const TextStyle(color: kRed, fontSize: 12)),
              ),
              const SizedBox(height: 16),
            ],

            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: _saveManual,
                child: const Padding(
                  padding: EdgeInsets.symmetric(vertical: 14),
                  child: Text('CONNECT', style: TextStyle(letterSpacing: 2, fontSize: 13)),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
