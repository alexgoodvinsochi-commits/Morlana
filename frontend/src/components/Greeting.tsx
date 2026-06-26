interface Props {
  zodiacSign: string;
  greeting: string;
  onNext: () => void;
}

export default function Greeting({ zodiacSign, greeting, onNext }: Props) {
  return (
    <div className="greeting">
      <h1>✨ Ваш астро-разбор</h1>
      <p className="zodiac-badge">Знак зодиака: {zodiacSign}</p>
      <div className="greeting-text">
        {greeting.split('\n').map((paragraph, i) => (
          paragraph.trim() ? <p key={i}>{paragraph}</p> : null
        ))}
      </div>
      <button onClick={onNext}>Далее → Расклад</button>
    </div>
  );
}
