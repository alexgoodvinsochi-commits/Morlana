const MAJOR_ARCANA = [
  'Шут', 'Маг', 'Верховная Жрица', 'Императрица', 'Император',
  'Иерофант', 'Влюблённые', 'Колесница', 'Сила', 'Отшельник',
  'Колесо Фортуны', 'Справедливость', 'Повешенный', 'Смерть',
  'Умеренность', 'Дьявол', 'Башня', 'Звезда', 'Луна', 'Солнце',
  'Суд', 'Мир',
];

const SUITS = ['cups', 'pents', 'swords', 'wands'] as const;

const SUIT_NAMES: Record<string, string> = {
  cups: 'Кубки',
  pents: 'Пентакли',
  swords: 'Мечи',
  wands: 'Жезлы',
};

const MINOR_RANKS = [
  'Туз', '2', '3', '4', '5', '6', '7', '8', '9', '10',
  'Паж', 'Рыцарь', 'Королева', 'Король',
];

function pad(n: number): string {
  return n.toString().padStart(2, '0');
}

export function getCardImage(number: number): string {
  if (number >= 1 && number <= 22) {
    return `/maj${pad(number - 1)}.jpg`;
  }
  const minorIndex = number - 23;
  const suitIndex = Math.floor(minorIndex / 14);
  const rankIndex = minorIndex % 14;
  const suit = SUITS[suitIndex];
  return `/${suit}${pad(rankIndex + 1)}.jpg`;
}

export function getCardName(number: number): string {
  if (number >= 1 && number <= 22) {
    return MAJOR_ARCANA[number - 1];
  }
  const minorIndex = number - 23;
  const suitIndex = Math.floor(minorIndex / 14);
  const rankIndex = minorIndex % 14;
  const suit = SUIT_NAMES[SUITS[suitIndex]];
  return `${MINOR_RANKS[rankIndex]} ${suit}`;
}
