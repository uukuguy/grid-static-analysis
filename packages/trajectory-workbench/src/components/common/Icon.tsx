type IconName = 'eye' | 'function' | 'spark';

const glyphs: Record<IconName, string> = { eye: '◉', function: 'ƒ', spark: '✦' };

export function Icon({ name }: { name: IconName }) {
  return <span aria-hidden="true" className="wb-icon">{glyphs[name]}</span>;
}
