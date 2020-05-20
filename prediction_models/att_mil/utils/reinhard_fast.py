import numpy as np
from skimage import color


class ReinhardNormalizer:
    """
    Normalize a patch stain to the target image using the method of:
    E. Reinhard, M. Adhikhmin, B. Gooch, and P. Shirley, ‘Color transfer between images’, IEEE Computer Graphics and Applications, vol. 21, no. 5, pp. 34–41, Sep. 2001.
    """

    def __init__(self):
        super().__init__()
        self.target_concentrations = np.array([[148.60, 41.56], [169.30, 9.01], [105.97, 6.67]])

    def fit(self, values):
        if values:
            self.target_concentrations = values
        return

    def transform(self, tile, whitemask):
        """
        Transform an image
        :param tile:
        :param whitemask
        :return:
        """

        whitemask = ~whitemask
        imagelab = color.rgb2lab(tile)

        imageL, imageA, imageB = np.split(np.asarray(imagelab), 3, axis=2)
        imageL = np.squeeze((imageL * 255.0) / 100.0, axis=2)
        imageA = np.squeeze(imageA + 128.0, axis=2)
        imageB = np.squeeze(imageB + 128.0, axis=2)

        imageLM = np.ma.MaskedArray(imageL, whitemask)
        imageAM = np.ma.MaskedArray(imageA, whitemask)
        imageBM = np.ma.MaskedArray(imageB, whitemask)
        # Sometimes STD is near 0, or 0; add epsilon to avoid div by 0 -NI

        epsilon = 1e-11
        imageLMean = imageLM.mean()
        imageLSTD = imageLM.std() + epsilon
        imageAMean = imageAM.mean()
        imageASTD = imageAM.std() + epsilon

        imageBMean = imageBM.mean()
        imageBSTD = imageBM.std() + epsilon

        # normalization in lab
        imageL = (imageL - imageLMean) / imageLSTD * self.target_concentrations[0][1] + self.target_concentrations[0][0]
        imageA = (imageA - imageAMean) / imageASTD * self.target_concentrations[1][1] + self.target_concentrations[1][0]
        imageB = (imageB - imageBMean) / imageBSTD * self.target_concentrations[2][1] + self.target_concentrations[2][0]

        # imagelab = cv.merge((imageL, imageA, imageB))
        imageL = np.clip((imageL * 100.0) / (255.0), 0, 100)
        imageA = np.clip(imageA - 128.0, -127, 127)
        imageB = np.clip(imageB - 128.0, -127, 127)
        imagelab = np.stack([imageL, imageA, imageB], axis=2)

        # Back to RGB space
        returnimage = np.clip(color.lab2rgb(imagelab) * 255.0, 0, 255)
        # Replace white pixels
        returnimage[whitemask] = tile[whitemask]
        return returnimage

    def get_norm_method(self):
        return "reinhard"