import 'package:flutter/material.dart';

const kBgDark    = Color(0xFF060E16);
const kBgCard    = Color(0xFF0D1F2E);
const kCyan      = Color(0xFF00D4FF);
const kCyanDim   = Color(0xFF0A6A7F);
const kAmber     = Color(0xFFFF9500);
const kGreen     = Color(0xFF39FF14);
const kRed       = Color(0xFFFF2D55);
const kTextPrim  = Color(0xFFE0F0FF);
const kTextDim   = Color(0xFF5A7A9A);
const kBorder    = Color(0xFF1A3A4A);

ThemeData albedoTheme() {
  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    scaffoldBackgroundColor: kBgDark,
    colorScheme: const ColorScheme.dark(
      primary:   kCyan,
      secondary: kAmber,
      surface:   kBgCard,
      error:     kRed,
    ),
    fontFamily: 'monospace',
    appBarTheme: const AppBarTheme(
      backgroundColor: kBgDark,
      foregroundColor: kCyan,
      elevation: 0,
      titleTextStyle: TextStyle(
        color: kCyan,
        fontSize: 14,
        fontWeight: FontWeight.bold,
        letterSpacing: 2.0,
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: kBgCard,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(4),
        borderSide: const BorderSide(color: kBorder),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(4),
        borderSide: const BorderSide(color: kCyan),
      ),
      hintStyle: const TextStyle(color: kTextDim),
      labelStyle: const TextStyle(color: kTextDim),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: kCyanDim,
        foregroundColor: kCyan,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
        textStyle: const TextStyle(letterSpacing: 1.5, fontWeight: FontWeight.bold),
      ),
    ),
    textTheme: const TextTheme(
      bodyMedium: TextStyle(color: kTextPrim),
      bodySmall:  TextStyle(color: kTextDim),
    ),
  );
}
