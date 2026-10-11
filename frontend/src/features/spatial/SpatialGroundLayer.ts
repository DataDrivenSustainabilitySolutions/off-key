import * as THREE from "three";

export const SPATIAL_GROUND_HEIGHT = -0.018;

const vertexShader = /* glsl */ `
  uniform mat4 uProjectionInverse;
  uniform mat4 uCameraWorld;
  varying vec3 vNearWorld;
  varying vec3 vFarWorld;

  void main() {
    // The frustum endpoints interpolate across the quad for both camera types.
    vec4 nearPoint = uProjectionInverse * vec4(position.xy, -1.0, 1.0);
    vec4 farPoint = uProjectionInverse * vec4(position.xy, 1.0, 1.0);
    vNearWorld = (uCameraWorld * vec4(nearPoint.xyz / nearPoint.w, 1.0)).xyz;
    vFarWorld = (uCameraWorld * vec4(farPoint.xyz / farPoint.w, 1.0)).xyz;
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`;

const fragmentShader = /* glsl */ `
  uniform mat4 uProjection;
  uniform float uNearClip;
  uniform float uFarClip;
  uniform float uGroundHeight;
  uniform vec3 uFloorColor;
  uniform vec3 uMinorColor;
  uniform vec3 uMajorColor;
  varying vec3 vNearWorld;
  varying vec3 vFarWorld;

  float gridLine(vec2 world, float spacing) {
    vec2 coordinate = world / spacing;
    vec2 footprint = max(fwidth(coordinate), vec2(0.000001));
    vec2 distance = abs(fract(coordinate - 0.5) - 0.5) / footprint;
    vec2 coverage = 1.0 - smoothstep(vec2(0.35), vec2(1.15), distance);
    // Fade each axis before its lines become subpixel and produce moire.
    coverage *= 1.0 - smoothstep(vec2(0.2), vec2(0.65), footprint);
    return max(coverage.x, coverage.y);
  }

  void main() {
    vec3 ray = vFarWorld - vNearWorld;
    // Keep derivatives defined on both sides of horizon/clip boundaries.
    float safeRayY = ray.y < 0.0 ? -max(abs(ray.y), 0.0000001) : max(abs(ray.y), 0.0000001);
    float alongRay = (uGroundHeight - vNearWorld.y) / safeRayY;
    vec3 world = vNearWorld + alongRay * ray;
    vec4 viewPoint = viewMatrix * vec4(world, 1.0);
    vec4 clip = uProjection * viewPoint;
    float safeW = clip.w < 0.0 ? -max(abs(clip.w), 0.0000001) : max(abs(clip.w), 0.0000001);
    float depth = 0.5 * (clip.z / safeW) + 0.5;
    float minor = gridLine(world.xz, 1.0);
    float major = gridLine(world.xz, 10.0);
    // Fade in linear camera depth, including perspective cameras. Fading the
    // grid to the exact background colour makes both clip edges invisible.
    float viewDepth = -viewPoint.z;
    float nearWidth = max(2.0, 8.0 * fwidth(viewDepth));
    float fade = smoothstep(uNearClip, uNearClip + nearWidth, viewDepth);
    fade *= 1.0 - smoothstep(0.7 * uFarClip, uFarClip, viewDepth);
    if (abs(ray.y) < 0.0000001 || alongRay < 0.0 || alongRay > 1.0) discard;
    if (clip.w <= 0.0 || depth < 0.0 || depth > 1.0) discard;
    gl_FragDepth = depth;
    vec3 color = mix(uFloorColor, uMinorColor, minor * fade);
    color = mix(color, uMajorColor, major * fade);
    gl_FragColor = vec4(color, 1.0);
    #include <colorspace_fragment>
  }
`;

/** An unbounded ground plane costs one draw call and two fixed triangles. */
export class SpatialGroundLayer {
  private readonly geometry = new THREE.PlaneGeometry(2, 2);
  private readonly uniforms = {
    uProjectionInverse: { value: new THREE.Matrix4() },
    uCameraWorld: { value: new THREE.Matrix4() },
    uProjection: { value: new THREE.Matrix4() },
    uNearClip: { value: 0.1 },
    uFarClip: { value: 400 },
    uGroundHeight: { value: SPATIAL_GROUND_HEIGHT },
    uFloorColor: { value: new THREE.Color("#f9fafb") },
    uMinorColor: { value: new THREE.Color("#e9edf0") },
    uMajorColor: { value: new THREE.Color("#dfe5e9") },
  };
  private readonly material = new THREE.ShaderMaterial({
    uniforms: this.uniforms,
    vertexShader,
    fragmentShader,
    depthTest: true,
    depthWrite: true,
    toneMapped: false,
  });
  readonly object = new THREE.Mesh(this.geometry, this.material);
  private disposed = false;

  constructor() {
    this.object.name = "spatial-ground";
    this.object.frustumCulled = false;
    this.object.renderOrder = -1000;
  }

  update(camera: THREE.OrthographicCamera | THREE.PerspectiveCamera) {
    if (this.disposed) return;
    camera.updateMatrixWorld();
    const uniforms = this.uniforms;
    if (!uniforms.uCameraWorld.value.equals(camera.matrixWorld))
      uniforms.uCameraWorld.value.copy(camera.matrixWorld);
    if (!uniforms.uProjection.value.equals(camera.projectionMatrix)) {
      uniforms.uProjection.value.copy(camera.projectionMatrix);
      uniforms.uProjectionInverse.value.copy(camera.projectionMatrixInverse);
    }
    uniforms.uNearClip.value = camera.near;
    uniforms.uFarClip.value = camera.far;
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.object.removeFromParent();
    this.geometry.dispose();
    this.material.dispose();
  }
}
