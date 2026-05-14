import React, { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, {
  cancelAnimation,
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from 'react-native-reanimated';
import Svg, { Circle, Defs, RadialGradient, Stop } from 'react-native-svg';
import { Colors } from '../theme';
import { VoiceStatus } from '../types';

interface Props {
  status: VoiceStatus;
}

const ORB = 180;
const CENTER = ORB / 2;
const CORE_R = CENTER - 8;

export function CentralOrb({ status }: Props) {
  const isMicActive = status === 'listening';
  const isProcessing = status === 'processing' || status === 'speaking';

  const scale = useSharedValue(1);
  const glowOpacity = useSharedValue(0.3);
  const ringOpacity = useSharedValue(0.15);

  useEffect(() => {
    cancelAnimation(scale);
    cancelAnimation(glowOpacity);
    cancelAnimation(ringOpacity);

    if (isMicActive) {
      // Fast urgent pulse while mic is open
      scale.value = withRepeat(
        withSequence(
          withTiming(1.14, { duration: 480, easing: Easing.inOut(Easing.ease) }),
          withTiming(1.0, { duration: 480, easing: Easing.inOut(Easing.ease) }),
        ),
        -1,
        false,
      );
      glowOpacity.value = withRepeat(
        withSequence(
          withTiming(1.0, { duration: 480 }),
          withTiming(0.6, { duration: 480 }),
        ),
        -1,
        false,
      );
      ringOpacity.value = withRepeat(
        withSequence(
          withTiming(0.55, { duration: 480 }),
          withTiming(0.2, { duration: 480 }),
        ),
        -1,
        false,
      );
    } else if (isProcessing) {
      // Slow clockwise-feeling shimmer while thinking
      scale.value = withRepeat(
        withSequence(
          withTiming(1.06, { duration: 900, easing: Easing.inOut(Easing.ease) }),
          withTiming(0.97, { duration: 900, easing: Easing.inOut(Easing.ease) }),
        ),
        -1,
        false,
      );
      glowOpacity.value = withRepeat(
        withSequence(
          withTiming(0.7, { duration: 900 }),
          withTiming(0.35, { duration: 900 }),
        ),
        -1,
        false,
      );
      ringOpacity.value = withTiming(0.25, { duration: 400 });
    } else {
      // Slow idle breath
      scale.value = withRepeat(
        withSequence(
          withTiming(1.05, { duration: 2400, easing: Easing.inOut(Easing.sin) }),
          withTiming(1.0, { duration: 2400, easing: Easing.inOut(Easing.sin) }),
        ),
        -1,
        false,
      );
      glowOpacity.value = withRepeat(
        withSequence(
          withTiming(0.45, { duration: 2400 }),
          withTiming(0.15, { duration: 2400 }),
        ),
        -1,
        false,
      );
      ringOpacity.value = withTiming(0.12, { duration: 800 });
    }
  }, [isMicActive, isProcessing]);

  const containerStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  const glow1Style = useAnimatedStyle(() => ({
    opacity: glowOpacity.value,
  }));

  const glow2Style = useAnimatedStyle(() => ({
    opacity: ringOpacity.value,
  }));

  const coreColor = isMicActive
    ? { inner: '#A0FFFF', mid: '#00E5FF', outer: '#0077CC' }
    : isProcessing
    ? { inner: '#60CCFF', mid: '#0099EE', outer: '#004488' }
    : { inner: '#4499FF', mid: '#0055BB', outer: '#031030' };

  return (
    <View style={styles.wrapper}>
      {/* Outermost diffuse bloom */}
      <Animated.View
        style={[
          styles.glowRing,
          { width: ORB + 100, height: ORB + 100, borderRadius: (ORB + 100) / 2 },
          isMicActive ? styles.bloomActiveFar : styles.bloomIdleFar,
          glow2Style,
        ]}
      />
      {/* Mid glow ring */}
      <Animated.View
        style={[
          styles.glowRing,
          { width: ORB + 48, height: ORB + 48, borderRadius: (ORB + 48) / 2 },
          isMicActive ? styles.bloomActiveMid : styles.bloomIdleMid,
          glow1Style,
        ]}
      />
      {/* Inner glow halo */}
      <Animated.View
        style={[
          styles.glowRing,
          { width: ORB + 16, height: ORB + 16, borderRadius: (ORB + 16) / 2 },
          isMicActive ? styles.bloomActiveNear : styles.bloomIdleNear,
          glow1Style,
        ]}
      />

      {/* Core orb SVG */}
      <Animated.View style={[styles.orb, containerStyle]}>
        <Svg width={ORB} height={ORB} viewBox={`0 0 ${ORB} ${ORB}`}>
          <Defs>
            <RadialGradient id="core" cx="38%" cy="32%" r="68%">
              <Stop offset="0%" stopColor={coreColor.inner} stopOpacity="1" />
              <Stop offset="45%" stopColor={coreColor.mid} stopOpacity="0.95" />
              <Stop offset="100%" stopColor={coreColor.outer} stopOpacity="0.88" />
            </RadialGradient>
            <RadialGradient id="rim" cx="50%" cy="50%" r="50%">
              <Stop offset="70%" stopColor="transparent" stopOpacity="0" />
              <Stop
                offset="100%"
                stopColor={isMicActive ? '#00F5FF' : '#1A6FCC'}
                stopOpacity="0.4"
              />
            </RadialGradient>
          </Defs>

          {/* Base sphere */}
          <Circle cx={CENTER} cy={CENTER} r={CORE_R} fill="url(#core)" />
          {/* Rim light */}
          <Circle cx={CENTER} cy={CENTER} r={CORE_R} fill="url(#rim)" />
          {/* Primary specular */}
          <Circle cx={CENTER - 22} cy={CENTER - 24} r={18} fill="rgba(255,255,255,0.13)" />
          {/* Tight specular pinpoint */}
          <Circle cx={CENTER - 16} cy={CENTER - 18} r={6} fill="rgba(255,255,255,0.28)" />
        </Svg>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    width: ORB + 100,
    height: ORB + 100,
    alignItems: 'center',
    justifyContent: 'center',
  },
  orb: {
    position: 'absolute',
  },
  glowRing: {
    position: 'absolute',
  },
  bloomIdleFar: { backgroundColor: 'rgba(20, 80, 200, 0.08)' },
  bloomIdleMid: { backgroundColor: 'rgba(20, 100, 220, 0.14)' },
  bloomIdleNear: { backgroundColor: 'rgba(30, 120, 240, 0.20)' },
  bloomActiveFar: { backgroundColor: 'rgba(0, 200, 255, 0.12)' },
  bloomActiveMid: { backgroundColor: 'rgba(0, 230, 255, 0.22)' },
  bloomActiveNear: { backgroundColor: 'rgba(0, 245, 255, 0.32)' },
});
