import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Polygon } from 'react-native-svg';
import { Colors, Typography } from '../theme';

const SIZE = 32;
const CENTER = SIZE / 2;

export function AlbedoAvatar() {
  return (
    <View style={styles.wrapper}>
      <Svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
        {/* Outer ring */}
        <Circle
          cx={CENTER}
          cy={CENTER}
          r={CENTER - 1}
          fill="none"
          stroke={Colors.cyan}
          strokeWidth={1}
          opacity={0.6}
        />
        {/* Inner fill */}
        <Circle cx={CENTER} cy={CENTER} r={CENTER - 4} fill={Colors.bgSurface} />
        {/* Spartan delta mark — three-point triangle */}
        <Polygon
          points={`${CENTER},${CENTER - 8} ${CENTER - 7},${CENTER + 5} ${CENTER + 7},${CENTER + 5}`}
          fill="none"
          stroke={Colors.cyan}
          strokeWidth={1.4}
          strokeLinejoin="round"
        />
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    width: SIZE,
    height: SIZE,
    marginRight: 8,
    marginTop: 2,
  },
});
