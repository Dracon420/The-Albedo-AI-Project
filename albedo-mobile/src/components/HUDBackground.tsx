import React from 'react';
import { StyleSheet, View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Colors } from '../theme';

export function HUDBackground({ children }: { children: React.ReactNode }) {
  return (
    <LinearGradient
      colors={[Colors.bg, Colors.bgMid, '#0A1A45']}
      locations={[0, 0.55, 1]}
      style={styles.gradient}
    >
      {/* Subtle radial bloom at top-center — gives the HUD a light-source feel */}
      <View style={styles.bloom} pointerEvents="none" />
      {children}
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  gradient: {
    flex: 1,
  },
  bloom: {
    position: 'absolute',
    top: -120,
    alignSelf: 'center',
    width: 420,
    height: 420,
    borderRadius: 210,
    backgroundColor: 'rgba(0, 80, 180, 0.12)',
  },
});
