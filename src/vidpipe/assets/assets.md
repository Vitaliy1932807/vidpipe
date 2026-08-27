# Блоки ассетов проекта

Три блока подставляются в КАЖДЫЙ промпт Flow, чтобы стиль не плыл по ролику.
Правь под конкретный проект: ENV меняется чаще всего.

Формат: парсер забирает всё от `[БЛОК]` до следующего `[БЛОК]`. Любая приписка
после блока уедет внутрь него и попадёт в промпты, поэтому пояснения держи
здесь, до первого блока. Читаются ровно три имени: STYLE, ENV, NEGATIVE.

Всё содержимое блоков — по-английски: генератор видео понимает английский
заметно лучше, а смешанный текст отрабатывает хуже однородного.

Строка «No objects newer than ГОД» в конце ENV держит эпоху надёжнее любых
прилагательных.

[STYLE]
cinematic documentary reenactment, shot on 35mm film, natural available light,
muted desaturated palette, fine film grain, shallow depth of field, 16:9

[ENV]
rural setting, mid-1990s. Overcast sky, damp air, muted earthy tones.
No objects newer than 1994.

[NEGATIVE]
no text, no captions, no subtitles, no legible writing, no watermarks,
no logos, no brand names, no modern clothing, no smartphones, no plastic,
no distorted faces, no extra limbs, no cartoon style
