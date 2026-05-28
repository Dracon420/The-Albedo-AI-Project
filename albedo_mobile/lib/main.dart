import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'screens/setup_screen.dart';
import 'screens/chat_screen.dart';
import 'theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final prefs = await SharedPreferences.getInstance();
  final isPaired = (prefs.getString('relay_url') ?? '').isNotEmpty &&
      (prefs.getString('token') ?? '').isNotEmpty;

  runApp(AlbedoApp(startPaired: isPaired));
}

class AlbedoApp extends StatelessWidget {
  final bool startPaired;
  const AlbedoApp({super.key, required this.startPaired});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Albedo',
      debugShowCheckedModeBanner: false,
      theme: albedoTheme(),
      initialRoute: startPaired ? '/chat' : '/setup',
      routes: {
        '/setup': (_) => const SetupScreen(),
        '/chat':  (_) => const ChatScreen(),
      },
    );
  }
}
