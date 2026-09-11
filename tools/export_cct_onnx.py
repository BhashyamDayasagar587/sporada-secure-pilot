import glob
import numpy as np
import onnxruntime as ort
from PIL import Image
from typing import List, Union


class CCT:
    def __init__(self, onnx_path: str, device: str = "cuda"):
        self.alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"
        self.pad_char = "_"
        self.max_plate_slots = 15

        self.img_height = 64
        self.img_width = 128
        self.num_channels = 3

        providers = (
            ["CUDAExecutionProvider"] if device == "cuda" else ["CPUExecutionProvider"]
        )

        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self.session = ort.InferenceSession(
            onnx_path, sess_options=so, providers=providers
        )

        # Auto-detect names
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

    def _preprocess(self, imgs):
        if isinstance(imgs, Image.Image):
            imgs = [imgs]

        batch = []
        for img in imgs:
            img = img.convert("RGB")
            img = img.resize((self.img_width, self.img_height))
            arr = np.array(img, dtype=np.float32)
            arr = np.transpose(arr, (2, 0, 1))

            batch.append(arr)

        return np.stack(batch, axis=0).astype(np.float32)

    def _decode_batch(self, logits: np.ndarray) -> List[str]:
        indices = np.argmax(logits, axis=-1)

        results = []
        for seq in indices:
            chars = [self.alphabet[i] for i in seq]
            plate = "".join(c for c in chars if c != self.pad_char)
            results.append(plate)

        return results

    def predict(self, img: Image.Image) -> str:
        batch = self._preprocess(img)

        outputs = self.session.run([self.output_name], {self.input_name: batch})

        return self._decode_batch(outputs[0])[0]

    def predict_batch(self, imgs: List[Image.Image]) -> List[str]:
        batch = self._preprocess(imgs)

        outputs = self.session.run([self.output_name], {self.input_name: batch})

        return self._decode_batch(outputs[0])


if __name__ == "__main__":
    model = CCT("./cct.onnx", device="cuda")

    images_path = glob.glob("./dataset/*.jpg")

    for image_path in images_path[:5]:
        with open(image_path.replace(".jpg", ".txt")) as f:
            gt = f.read().strip()

        image = Image.open(image_path)
        pred = model.predict(image)

        display(image)
        print("gt:", gt)
        print("pr:", pred)
        break
