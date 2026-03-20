"""
Скрипт для конвертации изображений портала в GIF с прозрачностью и анимацией открытия
"""

from PIL import Image, ImageSequence
import os
import sys

def convert_webp_to_gif(webp_path, output_path):
    """Конвертирует WebP в GIF с прозрачностью"""
    print(f"Конвертация {webp_path}...")
    
    img = Image.open(webp_path)
    
    # Конвертируем в RGBA если нужно
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    # Сохраняем как GIF с прозрачностью
    img.save(output_path, 'GIF', transparency=0, save_all=True)
    print(f"✅ Сохранено: {output_path}")
    return img

def convert_video_to_gif(video_path, output_path):
    """Конвертирует видео в GIF (требует moviepy или ffmpeg)"""
    print(f"Конвертация видео {video_path}...")
    
    try:
        from moviepy.editor import VideoFileClip
        
        clip = VideoFileClip(video_path)
        
        # Конвертируем в GIF
        clip.write_gif(output_path, fps=15, program='ffmpeg')
        clip.close()
        
        # Открываем и обрабатываем для прозрачности
        gif = Image.open(output_path)
        frames = []
        
        for frame in ImageSequence.Iterator(gif):
            # Конвертируем в RGBA
            frame = frame.convert('RGBA')
            
            # Делаем черный фон прозрачным
            data = frame.getdata()
            new_data = []
            for item in data:
                # Если пиксель черный (или очень темный), делаем прозрачным
                if item[0] < 30 and item[1] < 30 and item[2] < 30:
                    new_data.append((0, 0, 0, 0))
                else:
                    new_data.append(item)
            
            frame.putdata(new_data)
            frames.append(frame)
        
        # Сохраняем с прозрачностью
        if frames:
            frames[0].save(
                output_path,
                save_all=True,
                append_images=frames[1:],
                duration=clip.duration / len(frames) * 1000,
                loop=0,
                transparency=0
            )
        
        print(f"✅ Сохранено: {output_path}")
        return frames[0] if frames else None
        
    except ImportError:
        print("⚠️ moviepy не установлен. Устанавливаю...")
        os.system("pip install moviepy")
        return convert_video_to_gif(video_path, output_path)
    except Exception as e:
        print(f"❌ Ошибка конвертации видео: {e}")
        print("💡 Попробуйте установить ffmpeg: https://ffmpeg.org/download.html")
        return None

def create_opening_animation(gif_path, output_path, num_frames=20):
    """Создает анимацию открытия портала из маленькой точки"""
    print(f"Создание анимации открытия из {gif_path}...")
    
    # Открываем исходный GIF
    gif = Image.open(gif_path)
    frames = []
    
    # Получаем все кадры
    for frame in ImageSequence.Iterator(gif):
        frame = frame.convert('RGBA')
        frames.append(frame.copy())
    
    if not frames:
        print("❌ Не удалось загрузить кадры")
        return
    
    base_frame = frames[0]
    width, height = base_frame.size
    center_x, center_y = width // 2, height // 2
    
    # Создаем кадры анимации открытия
    opening_frames = []
    
    for i in range(num_frames):
        # Масштаб от 0.0 до 1.0
        scale = i / (num_frames - 1)
        scale = scale ** 0.5  # Ease-out эффект
        
        # Новый размер
        new_width = int(width * scale)
        new_height = int(height * scale)
        
        if new_width < 1 or new_height < 1:
            # Создаем пустой кадр
            frame = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        else:
            # Масштабируем базовый кадр
            scaled = base_frame.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Создаем новый кадр с прозрачным фоном
            frame = Image.new('RGBA', (width, height), (0, 0, 0, 0))
            
            # Центрируем
            x = (width - new_width) // 2
            y = (height - new_height) // 2
            
            # Вставляем масштабированный кадр
            frame.paste(scaled, (x, y), scaled)
        
        opening_frames.append(frame)
    
    # Добавляем оригинальные кадры после открытия
    all_frames = opening_frames + frames
    
    # Сохраняем как GIF
    all_frames[0].save(
        output_path,
        save_all=True,
        append_images=all_frames[1:],
        duration=50,  # 50ms на кадр (20 FPS)
        loop=0,
        transparency=0
    )
    
    print(f"✅ Анимация открытия сохранена: {output_path}")

def main():
    # Создаем папку для ассетов
    assets_dir = os.path.join(os.path.dirname(__file__), 'assets')
    os.makedirs(assets_dir, exist_ok=True)
    
    # Пути к исходным файлам
    webp_path = r"C:\Users\1\Downloads\tumblr_a4c3a1f2eefc25bb591d3ef78bdf5753_2ba290ef_500.webp"
    video_path = r"C:\Users\1\Downloads\tumblr_mm55e88N8H1rnir1do1_500.gif.mp4"
    
    # Проверяем существование файлов
    if not os.path.exists(webp_path):
        print(f"❌ Файл не найден: {webp_path}")
        return
    
    # Конвертируем WebP
    webp_gif = os.path.join(assets_dir, 'portal_static.gif')
    convert_webp_to_gif(webp_path, webp_gif)
    
    # Создаем анимацию открытия для WebP
    webp_opening = os.path.join(assets_dir, 'portal_opening.gif')
    create_opening_animation(webp_gif, webp_opening)
    
    # Конвертируем видео если существует
    if os.path.exists(video_path):
        video_gif = os.path.join(assets_dir, 'portal_animated.gif')
        result = convert_video_to_gif(video_path, video_gif)
        
        if result:
            # Создаем анимацию открытия для видео
            video_opening = os.path.join(assets_dir, 'portal_animated_opening.gif')
            create_opening_animation(video_gif, video_opening)
    
    print("\n✅ Конвертация завершена!")
    print(f"📁 Файлы сохранены в: {assets_dir}")

if __name__ == "__main__":
    main()
