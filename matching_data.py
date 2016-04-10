import logger
import numpy as np
import sharded_hdf5 as sh
import os
import cv2
import progress_bar as pb

log = logger.get()


def crop_patch(image, bbox, patch_size, padding, padding_noise, center_noise,
               random):
    """Get a crop of the image.
    
    Args:
    
        bbox: [left, top, right, bottom] 
        patch_size: [H, W]
    """
    left = bbox[0]
    top = bbox[1]
    right = bbox[2]
    bottom = bbox[3]
    size_x = right - left
    size_y = bottom - top
    im_height = image.shape[0]
    im_width = image.shape[1]

    pn_x = random.uniform(padding - padding_noise, padding + padding_noise)
    pn_y = random.uniform(padding - padding_noise, padding + padding_noise)
    cn_x = random.uniform(-center_noise, center_noise)
    cn_y = random.uniform(-center_noise, center_noise)

    left = left + (cn_x - pn_x) * size_x
    right = right + (cn_x + pn_x) * size_x
    top = top + (cn_y - pn_y) * size_y
    bottom = bottom + (cn_y + pn_y) * size_y

    left = max(0, left)
    right = min(right, im_width)
    top = max(0, top)
    bottom = min(bottom, im_height)
    image_crop = image[top: bottom + 1, left: right + 1, :]
    image_resize = cv2.resize(image_crop, (patch_size[1], patch_size[0]))

    return image_resize


def get_dataset(folder, opt, split='train', seqs=None):
    """Get matching dataset. 
    
    Args:

        folder: folder where the dataset is

        opt: dict
            patch_height: height of the extracted patch
            patch_width: width of the extracted patch
            center_noise: +/- noise of center shift (uniform), relative to size
            padding_noise: +/- noise of padding (uniform), relative to size
            padding_mean: mean of padding
            num_ex_pos: number of positive examples per sequence
            num_ex_neg: number of negative examples per sequence
            shuffle: shuffle the final dataset

        split: string, 'train': sequences 0 - 12, 'valid': sequences 13 - 20

        seqs: list of sequences.

    Returns:
        dataset: dict
            images_0: [B, H, W, 3], first instance patches
            images_1: [B, H, W, 3], second instance patches
            label: [B], 1/0, whether they are the same instance. 

    """
    patch_height = opt['patch_height']
    patch_width = opt['patch_width']
    center_noise = opt['center_noise']
    padding_noise = opt['padding_noise']
    padding_mean = opt['padding_mean']
    num_ex_pos = opt['num_ex_pos']
    num_ex_neg = opt['num_ex_neg']
    shuffle = opt['shuffle']

    dataset_pattern = os.path.join(folder, 'dataset-*')
    dataset_file = sh.ShardedFile.from_pattern_read(dataset_pattern)
    random = np.random.RandomState(2)
    dataset_images = []
    dataset_labels = []

    if split is not None:
        if split == 'train':
            seqs = range(13)
        elif split == 'valid':
            seqs = range(13, 21)
        else:
            raise Exception('Unknown split: {}'.format(split))
        pass

    with sh.ShardedFileReader(dataset_file) as reader:
        for seq_num in pb.get_iter(seqs):
            seq_data = reader[seq_num]
            images = seq_data['images_0']
            gt_bbox = seq_data['gt_bbox']
            num_obj = gt_bbox.shape[0]
            num_frames = gt_bbox.shape[1]
            output_images = np.zeros([num_ex_neg + num_ex_pos,
                                      2, patch_height, patch_width, 3],
                                     dtype='uint8')
            output_labels = np.zeros([num_ex_neg + num_ex_pos], dtype='uint8')
            dataset_images.append(output_images)
            dataset_labels.append(output_labels)

            for ii in xrange(num_ex_neg):
                obj_id1 = 0
                obj_id2 = 0
                while obj_id1 == obj_id2:
                    obj_id1 = int(np.floor(random.uniform(0, num_obj)))
                    obj_id2 = int(np.floor(random.uniform(0, num_obj)))
                    pass

                non_zero_frames1 = gt_bbox[obj_id1, :, 4].nonzero()[0]
                idx1 = np.floor(random.uniform(0,
                                               non_zero_frames1.shape[0]))
                frm1 = non_zero_frames1[idx1]

                non_zero_frames2 = gt_bbox[obj_id2, :, 4].nonzero()[0]
                idx2 = np.floor(random.uniform(0,
                                               non_zero_frames2.shape[0]))
                frm2 = non_zero_frames2[idx2]

                image1 = images[frm1]
                image2 = images[frm2]
                bbox1 = gt_bbox[obj_id1, frm1, :4]
                bbox2 = gt_bbox[obj_id2, frm2, :4]
                patch_size = [patch_height, patch_width]
                output_images[ii, 0] = crop_patch(
                    image1, bbox1, patch_size, padding_mean, padding_noise,
                    center_noise, random)
                output_images[ii, 1] = crop_patch(
                    image2, bbox2, patch_size, padding_mean, padding_noise,
                    center_noise, random)
                output_labels[ii] = 0
                pass

            for ii in xrange(num_ex_pos):
                frames = np.array([0])
                while frames.shape[0] <= 1:
                    obj_id = int(np.floor(random.uniform(0, num_obj)))
                    frames = gt_bbox[obj_id, :, 4].nonzero()[0]
                    pass

                idx1 = 0
                idx2 = 0
                while idx1 == idx2:
                    idx1 = int(np.floor(random.uniform(0, frames.shape[0])))
                    idx2 = int(np.floor(random.uniform(0, frames.shape[0])))
                    pass

                frm1 = frames[idx1]
                frm2 = frames[idx2]

                # print 'Pos', seq_num, obj_id, frm1, frm2

                jj = ii + num_ex_neg
                image1 = images[frm1]
                image2 = images[frm2]
                bbox1 = gt_bbox[obj_id, frm1, :4]
                bbox2 = gt_bbox[obj_id, frm2, :4]
                patch_size = [patch_height, patch_width]
                output_images[jj, 0] = crop_patch(
                    image1, bbox1, patch_size, padding_mean, padding_noise,
                    center_noise, random)
                output_images[jj, 1] = crop_patch(
                    image2, bbox2, patch_size, padding_mean, padding_noise,
                    center_noise, random)
                output_labels[jj] = 1
                pass
            pass
        pass

    num_ex = 0
    for ss in xrange(len(seqs)):
        num_ex += dataset_images[ss].shape[0]
        pass

    final_images = np.zeros([num_ex, 2, patch_height, patch_width, 3],
                            dtype='uint8')
    final_labels = np.zeros([num_ex], dtype='uint8')
    log.info('Image shape: {}'.format(final_images.shape))
    log.info('Label shape: {}'.format(final_labels.shape))

    counter = 0
    for ss in xrange(len(seqs)):
        _num_ex = dataset_images[ss].shape[0]
        final_images[counter: counter + _num_ex] = dataset_images[ss]
        final_labels[counter: counter + _num_ex] = dataset_labels[ss]
        counter += _num_ex
        pass

    if shuffle:
        idx = np.arange(num_ex)
        random.shuffle(idx)
        final_images = final_images[idx]
        final_labels = final_labels[idx]
        pass

    dataset = {
        'images_0': final_images[:, 0],
        'images_1': final_images[:, 1],
        'labels': final_labels
    }

    return dataset


if __name__ == '__main__':
    opt = {
        'patch_height': 48,
        'patch_width': 48,
        'center_noise': 0.2,
        'padding_noise': 0.2,
        'padding_mean': 0.2,
        'num_ex_pos': 100,
        'num_ex_neg': 100,
        'shuffle': True
    }

    d = get_dataset(
        '/ais/gobi3/u/mren/data/kitti/tracking/training', opt, 'train')

    print d