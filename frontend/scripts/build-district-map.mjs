import { mkdir, writeFile } from 'node:fs/promises'

// Generated asset: decode TopoJSON arcs, retain the 29 New Taipei districts,
// and preproject to SVG coordinates so no map library or remote tile service is needed.
const source = 'https://cdn.jsdelivr.net/npm/taiwan-atlas@2021.9.20/towns-10t.json'
const response = await fetch(source)
if (!response.ok) throw new Error(`Atlas download failed: ${response.status}`)
const topology = await response.json()
const geometries = topology.objects.towns.geometries.filter(item => item.properties.COUNTYNAME === '新北市')
if (geometries.length !== 29) throw new Error(`Expected 29 districts, found ${geometries.length}`)
const decodeArc = index => {
  let x = 0, y = 0
  const points = topology.arcs[index < 0 ? ~index : index].map(([dx, dy]) => {
    x += dx; y += dy
    const lon = x * topology.transform.scale[0] + topology.transform.translate[0]
    const lat = y * topology.transform.scale[1] + topology.transform.translate[1]
    return [lon * Math.PI / 180, -Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360))]
  })
  return index < 0 ? points.reverse() : points
}
const decodeRing = arcs => arcs.flatMap((arc, index) => {
  const points = decodeArc(arc)
  return index ? points.slice(1) : points
})
const decodeGeometry = item => ({
  name: item.properties.TOWNNAME,
  english: item.properties.TOWNENG,
  polygons: (item.type === 'Polygon' ? [item.arcs] : item.arcs).map(polygon => polygon.map(decodeRing)),
})
const decoded = geometries.map(decodeGeometry)
const allPoints = decoded.flatMap(item => item.polygons.flat(2))
const xs = allPoints.map(point => point[0]), ys = allPoints.map(point => point[1])
const minX = Math.min(...xs), minY = Math.min(...ys)
const scale = Math.min(550 / (Math.max(...xs) - minX), 490 / (Math.max(...ys) - minY))
const project = ([x, y]) => [+(25 + (x - minX) * scale).toFixed(1), +(25 + (y - minY) * scale).toFixed(1)]
const pathFor = polygons => polygons.flatMap(polygon => polygon.map(ring => ring.map((point, index) => `${index ? 'L' : 'M'}${project(point).join(',')}`).join('') + 'Z')).join('')
// An interior label anchor, not a bounding-box center (which can fall outside
// irregular coastal districts). Maximize clearance on a deterministic grid.
const anchorFor = polygons => {
  const projected = polygons.map(polygon => polygon.map(ring => ring.map(project)))
  const inRing = ([x, y], ring) => {
    let inside = false
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j]
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside
    }
    return inside
  }
  const distance = ([x, y], a, b) => {
    const dx = b[0] - a[0], dy = b[1] - a[1]
    const t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy || 1)))
    return Math.hypot(x - a[0] - t * dx, y - a[1] - t * dy)
  }
  let best = { point: projected[0][0][0], radius: 0 }
  for (const rings of projected) {
    const outer = rings[0], xs = outer.map(p => p[0]), ys = outer.map(p => p[1])
    const x0 = Math.min(...xs), y0 = Math.min(...ys), w = Math.max(...xs) - x0, h = Math.max(...ys) - y0
    for (let iy = 0; iy <= 24; iy++) for (let ix = 0; ix <= 24; ix++) {
      const point = [x0 + w * ix / 24, y0 + h * iy / 24]
      if (!inRing(point, outer) || rings.slice(1).some(ring => inRing(point, ring))) continue
      let radius = Infinity
      for (const ring of rings) for (let i = 0; i < ring.length - 1; i++) radius = Math.min(radius, distance(point, ring[i], ring[i + 1]))
      if (radius > best.radius) best = { point, radius }
    }
  }
  return { x: +best.point[0].toFixed(1), y: +best.point[1].toFixed(1), clearance: +best.radius.toFixed(1) }
}
const districts = decoded.sort((a, b) => a.english.localeCompare(b.english)).map((item, index) => ({
  name: item.name, english: item.english, number: index + 1,
  path: pathFor(item.polygons), label: anchorFor(item.polygons),
}))
const neighbors = topology.objects.counties.geometries
  .filter(item => ['臺北市', '台北市', '基隆市'].includes(item.properties.COUNTYNAME))
  .map(item => {
    const { polygons } = decodeGeometry(item)
    return { name: item.properties.COUNTYNAME, english: item.properties.COUNTYENG, path: pathFor(polygons), label: anchorFor(polygons) }
  })
if (neighbors.length !== 2) throw new Error('Expected Taipei City and Keelung City context geometry')
const output = new URL('../src/data/', import.meta.url)
await mkdir(output, { recursive: true })
await writeFile(new URL('district-map.json', output), JSON.stringify({
  source, edition: '2021.9.20', viewBox: '0 0 600 540', districts, neighbors,
}) + '\n')
console.log(`Generated ${districts.length} district paths (${JSON.stringify(districts).length} characters).`)
