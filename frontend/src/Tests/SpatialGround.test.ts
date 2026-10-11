import { describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import {
  SpatialGroundLayer,
  SPATIAL_GROUND_HEIGHT,
} from "../features/spatial/SpatialGroundLayer";

type GroundCamera = THREE.OrthographicCamera | THREE.PerspectiveCamera;
const groundPlane = new THREE.Plane(
  new THREE.Vector3(0, 1, 0),
  -SPATIAL_GROUND_HEIGHT,
);

function camera(perspective = false): GroundCamera {
  const result = perspective
    ? new THREE.PerspectiveCamera(55, 4 / 3, 0.1, 400)
    : new THREE.OrthographicCamera(-20, 20, 15, -15, 0.1, 400);
  result.position.set(22, 28, 30);
  result.lookAt(0, 0, 0);
  result.updateMatrixWorld();
  return result;
}

// Probe the supplied shader matrices and interpolated quad endpoints without
// requiring a WebGL context. Raycaster provides the independent expected ray.
function endpoint(layer: SpatialGroundLayer, x: number, y: number, z: number) {
  const uniforms = layer.object.material.uniforms;
  const point = new THREE.Vector4(x, y, z, 1).applyMatrix4(
    uniforms.uProjectionInverse!.value,
  );
  point.divideScalar(point.w);
  point.applyMatrix4(uniforms.uCameraWorld!.value);
  return new THREE.Vector3(point.x, point.y, point.z);
}

function interpolatedEndpoint(
  layer: SpatialGroundLayer,
  ndc: THREE.Vector2,
  z: number,
) {
  const result = new THREE.Vector3();
  for (const x of [-1, 1])
    for (const y of [-1, 1]) {
      const weight = ((1 + x * ndc.x) * (1 + y * ndc.y)) / 4;
      result.addScaledVector(endpoint(layer, x, y, z), weight);
    }
  return result;
}

function sample(layer: SpatialGroundLayer, ndc: THREE.Vector2) {
  const near = interpolatedEndpoint(layer, ndc, -1);
  const far = interpolatedEndpoint(layer, ndc, 1);
  const ray = far.sub(near);
  if (Math.abs(ray.y) < 1e-7) return null;
  const alongRay = (SPATIAL_GROUND_HEIGHT - near.y) / ray.y;
  if (alongRay < 0 || alongRay > 1) return null;
  const point = near.addScaledVector(ray, alongRay);
  const uniforms = layer.object.material.uniforms;
  const view = uniforms.uCameraWorld!.value.clone().invert();
  const clip = new THREE.Vector4(point.x, point.y, point.z, 1)
    .applyMatrix4(view)
    .applyMatrix4(uniforms.uProjection!.value);
  const depth = (clip.z / clip.w + 1) / 2;
  return clip.w > 0 && depth >= 0 && depth <= 1 ? { point, depth } : null;
}

function expectedGround(camera: GroundCamera, ndc: THREE.Vector2) {
  const raycaster = new THREE.Raycaster();
  raycaster.setFromCamera(ndc, camera);
  return raycaster.ray.intersectPlane(groundPlane, new THREE.Vector3());
}

describe("unbounded spatial ground", () => {
  it.each([false, true])(
    "reconstructs floor rays and real projected depth with perspective=%s",
    (perspective) => {
      const layer = new SpatialGroundLayer();
      const view = camera(perspective);
      try {
        layer.update(view);
        for (const [x, y] of [
          [0, 0],
          [-0.71, -0.4],
          [0.62, 0.37],
        ]) {
          const ndc = new THREE.Vector2(x, y);
          const actual = sample(layer, ndc)!;
          const expected = expectedGround(view, ndc)!;
          expect(actual.point.distanceTo(expected)).toBeLessThan(1e-8);
          const projected = actual.point.clone().project(view);
          expect(projected.x).toBeCloseTo(x!, 10);
          expect(projected.y).toBeCloseTo(y!, 10);
          expect(actual.depth).toBeCloseTo((projected.z + 1) / 2, 12);
        }
      } finally {
        layer.dispose();
      }
    },
  );

  it("covers a top view far outside the old grid without changing its geometry", () => {
    const layer = new SpatialGroundLayer();
    const view = new THREE.OrthographicCamera(-200, 200, 150, -150, 0.1, 800);
    const geometry = layer.object.geometry;
    view.position.set(8000, 200, -8999.99);
    view.lookAt(8000, 0, -9000);
    view.zoom = 0.2;
    view.updateProjectionMatrix();
    try {
      layer.update(view);
      const ndc = new THREE.Vector2(0.7, -0.6);
      const actual = sample(layer, ndc)!;
      expect(actual.point.distanceTo(expectedGround(view, ndc)!)).toBeLessThan(
        1e-8,
      );
      expect(Math.abs(actual.point.x)).toBeGreaterThan(150);
      expect(Math.abs(actual.point.z)).toBeGreaterThan(150);
      expect(layer.object.geometry).toBe(geometry);
    } finally {
      layer.dispose();
    }
  });

  it("places the floor behind objects and group tiles at the same screen position", () => {
    const layer = new SpatialGroundLayer();
    const view = camera(true);
    const ndc = new THREE.Vector2(0.2, -0.1);
    try {
      layer.update(view);
      const floor = sample(layer, ndc)!;
      const raycaster = new THREE.Raycaster();
      raycaster.setFromCamera(ndc, view);
      for (const height of [0.059, 1.25]) {
        const objectPoint = raycaster.ray.intersectPlane(
          new THREE.Plane(new THREE.Vector3(0, 1, 0), -height),
          new THREE.Vector3(),
        )!;
        const objectDepth = (objectPoint.project(view).z + 1) / 2;
        expect(objectDepth).toBeLessThan(floor.depth);
      }
      expect(layer.object.material.depthTest).toBe(true);
      expect(layer.object.material.depthWrite).toBe(true);
      expect(layer.object.renderOrder).toBeLessThan(0);
    } finally {
      layer.dispose();
    }
  });

  it("rejects rays above the horizon and floor intersections outside the clip range", () => {
    const layer = new SpatialGroundLayer();
    try {
      const horizon = new THREE.PerspectiveCamera(60, 1, 0.1, 100);
      horizon.position.set(0, 5, 0);
      horizon.lookAt(0, 5, -10);
      layer.update(horizon);
      expect(sample(layer, new THREE.Vector2(0, 0.8))).toBeNull();
      expect(sample(layer, new THREE.Vector2(0, 0))).toBeNull();
      expect(sample(layer, new THREE.Vector2(0, -0.8))).not.toBeNull();

      const clipped = new THREE.OrthographicCamera(-10, 10, 10, -10, 0.1, 5);
      clipped.position.set(0, 10, 0.01);
      clipped.lookAt(0, 0, 0);
      layer.update(clipped);
      expect(sample(layer, new THREE.Vector2())).toBeNull();
      clipped.near = 20;
      clipped.far = 100;
      clipped.updateProjectionMatrix();
      layer.update(clipped);
      expect(sample(layer, new THREE.Vector2())).toBeNull();
    } finally {
      layer.dispose();
    }
  });

  it("copies changed camera matrices while keeping uniforms and resources fixed", () => {
    const layer = new SpatialGroundLayer();
    const view = camera();
    const uniforms = layer.object.material.uniforms;
    const matrix = uniforms.uCameraWorld!.value;
    const geometry = layer.object.geometry;
    const material = layer.object.material;
    try {
      layer.update(view);
      const unchanged = matrix.clone();
      layer.update(view);
      expect(matrix.equals(unchanged)).toBe(true);
      view.position.x += 4000;
      view.zoom = 0.05;
      view.near = 0.25;
      view.far = 16000;
      view.updateProjectionMatrix();
      layer.update(view);
      expect(uniforms.uCameraWorld!.value).toBe(matrix);
      expect(matrix.equals(view.matrixWorld)).toBe(true);
      expect(
        uniforms.uProjectionInverse!.value.equals(view.projectionMatrixInverse),
      ).toBe(true);
      expect(uniforms.uProjection!.value.equals(view.projectionMatrix)).toBe(
        true,
      );
      expect(uniforms.uNearClip!.value).toBe(0.25);
      expect(uniforms.uFarClip!.value).toBe(16000);
      expect(layer.object.geometry).toBe(geometry);
      expect(layer.object.material).toBe(material);
      expect(geometry.getAttribute("position").count).toBe(4);
      expect(geometry.index!.count).toBe(6);
      expect(layer.object.children).toHaveLength(0);
      expect(layer.object.frustumCulled).toBe(false);
    } finally {
      layer.dispose();
    }
  });

  it("uses the exact scene floor colour and the renderer's output colour conversion", () => {
    const layer = new SpatialGroundLayer();
    try {
      const material = layer.object.material;
      expect(
        material.uniforms.uFloorColor!.value.equals(new THREE.Color("#f9fafb")),
      ).toBe(true);
      expect(material.toneMapped).toBe(false);
      // ShaderMaterial needs this chunk; otherwise linear uniforms darken the
      // floor and reveal its far-plane boundary against the sRGB background.
      expect(material.fragmentShader).toContain(
        "#include <colorspace_fragment>",
      );
      expect(material.fragmentShader).toContain("gl_FragDepth = depth");
    } finally {
      layer.dispose();
    }
  });

  it("releases its two GPU resources once and removes the mesh from the scene", () => {
    const layer = new SpatialGroundLayer();
    const scene = new THREE.Scene();
    const geometryDisposed = vi.fn();
    const materialDisposed = vi.fn();
    layer.object.geometry.addEventListener("dispose", geometryDisposed);
    layer.object.material.addEventListener("dispose", materialDisposed);
    scene.add(layer.object);
    layer.dispose();
    layer.dispose();
    expect(geometryDisposed).toHaveBeenCalledTimes(1);
    expect(materialDisposed).toHaveBeenCalledTimes(1);
    expect(scene.children).toHaveLength(0);
  });
});
