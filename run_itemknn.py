'''
@Author: Yu Di
@Date: 2019-12-03 12:30:14
@LastEditors: Yudi
@LastEditTime: 2019-12-03 14:45:25
@Company: Cardinal Operation
@Email: yudi@shanshu.ai
@Description: 
'''
import random
import argparse
import numpy as np
import pandas as pd
from tqdm import tqdm
from collections import defaultdict

from daisy.model.KNNRecommender import KNNWithMeans
from daisy.utils.loader import load_rate, split_test, split_validation, get_ur
from daisy.utils.metrics import precision_at_k, recall_at_k, map_at_k, hr_at_k, mrr_at_k, ndcg_at_k

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Item-KNN recommender test')
    # common settings
    parser.add_argument('--dataset', 
                        type=str, 
                        default='ml-100k', 
                        help='select dataset')
    parser.add_argument('--prepro', 
                        type=str, 
                        default='origin', 
                        help='dataset preprocess op.: origin/5core/10core')
    parser.add_argument('--topk', 
                        type=int, 
                        default=10, 
                        help='top number of recommend list')
    parser.add_argument('--test_method', 
                        type=str, 
                        default='fo', 
                        help='method for split test,options: loo/fo/tfo/tloo')
    parser.add_argument('--test_size', 
                        type=float, 
                        default=.2, 
                        help='split ratio for test set')
    parser.add_argument('--val_method', 
                        type=str, 
                        default='cv', 
                        help='validation method, options: cv, tfo, loo, tloo')
    parser.add_argument('--fold_num', 
                        type=int, 
                        default=5, 
                        help='No. of folds for cross-validation')
    parser.add_argument('--cand_num', 
                        type=int, 
                        default=1000, help='No. of candidates item for predict')
    # algo settings
    parser.add_argument('--sim_method', 
                        type=str, 
                        default='cosine', 
                        help='method to calculate similarity, options: cosine/jaccard/pearson')
    parser.add_argument('--maxk', 
                        type=int, 
                        default=40, 
                        help='The (max) number of neighbors to take into account')
    parser.add_argument('--mink', 
                        type=int, 
                        default=1, 
                        help='The (min) number of neighbors to take into account')
    args = parser.parse_args()

    '''Validation Process for Parameter Tuning'''
    df, user_num, item_num = load_rate(args.dataset, args.prepro, binary=False)
    train_set, test_set = split_test(df, args.test_method, args.test_size)
    
    # get ground truth
    test_ur = get_ur(test_set)
    total_train_ur = get_ur(train_set)

    train_set_list, val_set_list, fn = split_validation(train_set, 
                                                        args.val_method, 
                                                        args.fold_num)

    # initial candidate item pool
    item_pool = set(range(item_num))
    candidates_num = args.cand_num

    # store metrics result for test set
    fnl_precision, fnl_recall, fnl_map, fnl_ndcg, fnl_hr, fnl_mrr = [], [], [], [], [], []
    best_metric = np.array([0. for _ in range(6)])
    best_model, best_tag = None, None
    for fold in range(fn):
        print(f'Start Validation [{fold + 1}]......')
        train = train_set_list[fold]
        validation = val_set_list[fold]

        # build recommender model
        model = KNNWithMeans(user_num, item_num, 
                               args.maxk, args.mink, 
                               sim_options={'name': args.sim_method, 'user_based': False})
        model.fit(train)

        # get ground truth
        train_ur = get_ur(train)
        val_ur = get_ur(validation)

        # build candidates set
        assert max([len(v) for v in val_ur.values()]) < candidates_num, 'Small candidates_num setting'
        val_ucands = defaultdict(list)
        for k, v in val_ur.items():
            sample_num = candidates_num - len(v)
            sub_item_pool = item_pool - v - train_ur[k] # remove GT & interacted
            samples = random.sample(sub_item_pool, sample_num)
            val_ucands[k] = list(v | set(samples))

        # get predict result
        preds = {}
        for u in tqdm(val_ucands.keys()):
            pred_rates = [model.predict(u, i)[0] for i in val_ucands[u]]
            rec_idx = np.argsort(pred_rates)[::-1][:args.topk]
            top_n = np.array(val_ucands[u])[rec_idx]
            preds[u] = top_n

        # convert rank list to binary-interaction
        for u in preds.keys():
            preds[u] = [1 if i in val_ur[u] else 0 for i in preds[u]]

        # calculate metrics for validation set
        pre_k = np.mean([precision_at_k(r, args.topk) for r in preds.values()])
        rec_k = recall_at_k(preds, val_ur, args.topk)
        hr_k = hr_at_k(preds, val_ur)
        map_k = map_at_k(preds.values())
        mrr_k = mrr_at_k(preds, args.topk)
        ndcg_k = np.mean([ndcg_at_k(r, args.topk) for r in preds.values()])
        
        print('-'*20)
        print(f'Precision@{args.topk}: {pre_k:.4f}')
        print(f'Recall@{args.topk}: {rec_k:.4f}')
        print(f'MAP@{args.topk}: {hr_k:.4f}')
        print(f'NDCG@{args.topk}: {map_k:.4f}')
        print(f'HR@{args.topk}: {mrr_k:.4f}')
        print(f'MRR@{args.topk}: {ndcg_k:.4f}')

        tmp_metric = np.array([pre_k, rec_k, hr_k, map_k, mrr_k, ndcg_k])

        if sum(tmp_metric >= best_metric) >= 3:
            best_model = model
            best_metric = tmp_metric
            best_tag = fold + 1

        print(f'Model build by Validation [{best_tag}] is best......', '\n')

    '''Test Process for Metrics Exporting'''
    print('='*50, '\n')
    print('Start Calculating Metrics......')
    # build candidates set
    assert max([len(v) for v in test_ur.values()]) < candidates_num, 'Small candidates_num setting'
    test_ucands = defaultdict(list)
    for k, v in test_ur.items():
        sample_num = candidates_num - len(v)
        sub_item_pool = item_pool - v - total_train_ur[k] # remove GT & interacted
        samples = random.sample(sub_item_pool, sample_num)
        test_ucands[k] = list(v | set(samples))

    # get predict result
    preds = {}
    for u in tqdm(test_ucands.keys()):
        pred_rates = [best_model.predict(u, i)[0] for i in test_ucands[u]]
        rec_idx = np.argsort(pred_rates)[::-1][:args.topk]
        top_n = np.array(test_ucands[u])[rec_idx]
        preds[u] = top_n

    # convert rank list to binary-interaction
    for u in preds.keys():
        preds[u] = [1 if i in test_ur[u] else 0 for i in preds[u]]
        
    # calculate metrics for test set
    pre_k = np.mean([precision_at_k(r, args.topk) for r in preds.values()])
    rec_k = recall_at_k(preds, test_ur, args.topk)
    hr_k = hr_at_k(preds, test_ur)
    map_k = map_at_k(preds.values())
    mrr_k = mrr_at_k(preds, args.topk)
    ndcg_k = np.mean([ndcg_at_k(r, args.topk) for r in preds.values()])

    print(f'Precision@{args.topk}: {pre_k:.4f}')
    print(f'Recall@{args.topk}: {rec_k:.4f}')
    print(f'MAP@{args.topk}: {hr_k:.4f}')
    print(f'NDCG@{args.topk}: {map_k:.4f}')
    print(f'HR@{args.topk}: {mrr_k:.4f}')
    print(f'MRR@{args.topk}: {ndcg_k:.4f}')
    print('='* 20, ' Done ', '='*20)
