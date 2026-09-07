from __future__ import annotations

from pathlib import Path


class ImagePdfConverter:
    def convert(self, image_paths: list[Path], output_path: Path) -> None:
        if not image_paths:
            raise ValueError("至少需要一个图片文件")

        from PIL import Image

        pages = []
        for path in image_paths:
            with Image.open(path) as image:
                pages.append(image.convert("RGB").copy())

        first, *rest = pages
        output_path.parent.mkdir(parents=True, exist_ok=True)
        first.save(output_path, "PDF", save_all=True, append_images=rest)
