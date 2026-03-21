"""
Простой скрипт для конвертации изображений портала в GIF
"""

from PIL import Image
import os

def convert_to_gif(input_path, output_path):
    """Конвертирует изображение в GIF с прозрачностью"""
    print(f"Конвертация {input_path}...")
    
    img = Image.open(input_path)
    
    # Конвертируем в RGBA если нужно
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    # Сохраняем как GIF
    img.save(output_path, 'GIF', save_all=True)
    print(f"✅ Сохранено: {output_path}")
    return img

def create_opening_animation(gif_path, output_path, num_frames=20):
    """Создает анимацию открытия из статичного GIF"""
    from PIL import ImageSequence
    
    print(f"Создание анимации открытия...")
    
    gif = Image.open(gif_path)
    base_frame = None
    
    # Берем первый кадр
    for frame in ImageSequence.Iterator(gif):
        base_frame = frame.convert('RGBA')
        break
    
    if not base_frame:
        print("❌ Не удалось загрузить кадр")
        return
    
    width, height = base_frame.size
    opening_frames = []
    
    # Создаем кадры открытия
    for i in range(num_frames):
        scale = (i / (num_frames - 1)) ** 0.5  # Ease-out
        
        new_width = int(width * scale)
        new_height = int(height * scale)
        
        if new_width < 1 or new_height < 1:
            frame = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        else:
            scaled = base_frame.resize((new_width, new_height), Image.Resampling.LANCZOS)
            frame = Image.new('RGBA', (width, height), (0, 0, 0, 0))
            x = (width - new_width) // 2
            y = (height - new_height) // 2
            frame.paste(scaled, (x, y), scaled)
        
        opening_frames.append(frame)
    
    # Сохраняем
    opening_frames[0].save(
        output_path,
        save_all=True,
        append_images=opening_frames[1:],
        duration=50,
        loop=0
    )
    
    print(f"✅ Анимация открытия сохранена: {output_path}")

# Конвертируем файлы
assets_dir = os.path.join(os.path.dirname(__file__), 'assets')
os.makedirs(assets_dir, exist_ok=True)

webp_path = r"C:\Users\1\Downloads\tumblr_a4c3a1f2eefc25bb591d3ef78bdf5753_2ba290ef_500.webp"
video_path = r"C:\Users\1\Downloads\tumblr_mm55e88N8H1rnir1do1_500.gif.mp4"

if os.path.exists(webp_path):
    # Конвертируем WebP
    static_gif = os.path.join(assets_dir, 'portal_static.gif')
    convert_to_gif(webp_path, static_gif)
    
    # Создаем анимацию открытия
    opening_gif = os.path.join(assets_dir, 'portal_opening.gif')
    create_opening_animation(static_gif, opening_gif)
    print("\n✅ Готово! Поместите GIF файлы в папку assets/")

if os.path.exists(video_path):
    print(f"\n💡 Видео портала: {video_path}")
    print("   Используй: python import_portal_from_mp4.py \"<путь к .mp4>\"")
