"""Test two hypotheses against the team-of-clones sim sample:

  H1: GAP rating drives 2B+3B production (extra-base "gap" hits).
  H2: SPEED rating drives the proportion of (2B+3B) that become triples.

Inputs the sample inline (parsed from the user-pasted TSV). Reports
each regression's coefficient, R^2, p-value, and a brief scatter
description for sanity.
"""
import io

import numpy as np
import pandas as pd
from scipy import stats

# --- Inline data (the user's calibration-sheet sample) --------------------
# Pasted exactly as supplied. NaN-safe parsing handled below.
DATA_TSV = """Name\tOrg\tLevel\tPos\tAge\tBats\tAVG\tOBP\tSLG\tOPS\twOBA\tPA\tAB\t1B\t2B\t3B\tHR\tBB\tHBP\tSO\tGO+FO\tBABIP\t2+3\t3_ratio\tBABIPvR\tBABIPvL\tK-avoidvR\tK-avoidvL\tPowervR\tPowervL\tEyevR\tEyevL\tGapvR\tGapvL\tSpeed
Alejandro Kirk\tTOR\tMLB\tC\t27\tR\t0.265\t0.345\t0.395\t0.740\t0.330\t617\t550\t109\t20\t0\t17\t63\t4\t85\t319\t0.288\t20\t0\t45\t45\t70\t70\t45\t50\t55\t60\t40\t40\t20
Alexander Huerta\tHOU\tMLB\tC\t17\tR\t0.116\t0.138\t0.129\t0.267\t0.122\t564\t550\t59\t4\t0\t1\t10\t4\t267\t219\t0.223\t4\t0\t20\t25\t20\t25\t20\t20\t20\t25\t20\t25\t30
Cal Raleigh\tSEA\tMLB\tC\t29\tS\t0.240\t0.329\t0.513\t0.842\t0.365\t623\t550\t72\t15\t0\t45\t69\t4\t164\t254\t0.255\t15\t0\t35\t30\t40\t45\t80\t80\t65\t55\t40\t40\t30
Gary Sanchez\tMIL\tMLB\tC\t33\tR\t0.233\t0.304\t0.442\t0.745\t0.327\t606\t550\t79\t16\t0\t33\t44\t12\t159\t263\t0.266\t16\t0\t40\t35\t45\t45\t70\t65\t40\t45\t40\t45\t25
Giaconino Lasaracina\tTOR\tMLB\tC\t22\tR\t0.165\t0.205\t0.220\t0.425\t0.192\t577\t550\t75\t9\t0\t7\t24\t3\t214\t245\t0.254\t9\t0\t35\t35\t30\t30\t35\t35\t35\t35\t30\t30\t30
J.C. Escarra\tNYY\tMLB\tC\t30\tL\t0.238\t0.316\t0.373\t0.689\t0.308\t613\t550\t91\t22\t2\t16\t57\t6\t112\t307\t0.272\t24\t0.083333333\t40\t35\t60\t55\t50\t40\t55\t50\t45\t50\t55
Jeans Carrizalez\tHOU\tMLB\tC\t17\tL\t0.116\t0.123\t0.129\t0.252\t0.112\t554\t550\t59\t4\t0\t1\t1\t3\t262\t224\t0.219\t4\t0\t20\t20\t20\t20\t20\t20\t25\t25\t25\t20\t30
Will Smith\tLAD\tMLB\tC\t30\tR\t0.264\t0.362\t0.451\t0.813\t0.359\t635\t550\t94\t25\t0\t26\t76\t9\t120\t285\t0.295\t25\t0\t50\t45\t55\t60\t60\t60\t65\t75\t50\t50\t30
William Contreras\tMIL\tMLB\tC\t28\tR\t0.275\t0.361\t0.442\t0.802\t0.354\t624\t550\t100\t30\t1\t20\t72\t2\t117\t282\t0.316\t31\t0.032258065\t60\t60\t55\t60\t50\t55\t60\t70\t50\t60\t30
Yainer Diaz\tHOU\tMLB\tC\t27\tR\t0.276\t0.309\t0.449\t0.758\t0.330\t576\t550\t102\t27\t1\t22\t24\t2\t104\t294\t0.307\t28\t0.035714286\t55\t55\t60\t65\t55\t55\t30\t40\t45\t50\t40
Bryce Harper\tPHI\tMLB\t1B\t33\tL\t0.278\t0.364\t0.496\t0.860\t0.375\t624\t550\t90\t34\t1\t28\t70\t4\t130\t267\t0.32\t35\t0.028571429\t60\t60\t55\t50\t65\t60\t65\t60\t70\t70\t35
Luis Arraez\tSF\tMLB\t1B\t28\tL\t0.304\t0.342\t0.393\t0.735\t0.324\t582\t550\t130\t30\t2\t5\t29\t3\t37\t346\t0.318\t32\t0.0625\t60\t55\t90\t85\t30\t25\t35\t35\t45\t40\t45
Pete Alonso\tBAL\tMLB\t1B\t31\tR\t0.282\t0.352\t0.549\t0.902\t0.389\t610\t550\t83\t34\t1\t37\t50\t10\t129\t266\t0.308\t35\t0.028571429\t55\t50\t50\t50\t75\t75\t45\t50\t75\t80\t25
Vladimir Guerrero Jr.\tTOR\tMLB\t1B\t26\tR\t0.293\t0.373\t0.524\t0.896\t0.389\t620\t550\t99\t29\t1\t32\t66\t4\t93\t296\t0.304\t30\t0.033333333\t55\t50\t65\t70\t65\t70\t55\t65\t50\t50\t25
Ketel Marte\tAZ\tMLB\t2B\t32\tS\t0.269\t0.354\t0.476\t0.830\t0.363\t622\t550\t90\t29\t2\t27\t67\t5\t105\t297\t0.29\t31\t0.064516129\t45\t45\t60\t65\t60\t65\t60\t55\t60\t70\t50
Nasim Nunez\tWSH\tMLB\t2B\t25\tS\t0.224\t0.305\t0.282\t0.586\t0.269\t614\t550\t103\t13\t2\t5\t62\t2\t144\t283\t0.295\t15\t0.133333333\t50\t45\t45\t50\t30\t30\t55\t55\t35\t35\t65
Nico Hoerner\tCHC\tMLB\t2B\t28\tR\t0.287\t0.342\t0.393\t0.735\t0.325\t596\t550\t119\t28\t3\t8\t39\t7\t59\t333\t0.310\t31\t0.096774194\t55\t60\t80\t80\t35\t40\t40\t40\t45\t50\t55
Tyler Tolbert\tKC\tMLB\t2B\t28\tR\t0.220\t0.279\t0.305\t0.584\t0.263\t595\t550\t91\t19\t5\t6\t37\t8\t168\t261\t0.307\t24\t0.208333333\t55\t55\t40\t40\t30\t30\t40\t40\t45\t45\t90
Jose Ramirez\tCLE\tMLB\t3B\t33\tS\t0.276\t0.339\t0.478\t0.817\t0.356\t602\t550\t94\t30\t3\t25\t49\t3\t83\t315\t0.288\t33\t0.090909091\t45\t45\t70\t70\t60\t60\t45\t45\t60\t65\t55
Junior Caminero\tTB\tMLB\t3B\t22\tR\t0.275\t0.328\t0.505\t0.834\t0.361\t594\t550\t94\t22\t0\t35\t42\t2\t112\t287\t0.288\t22\t0\t45\t45\t60\t65\t70\t75\t40\t45\t45\t50\t25
Max Muncy\tLAD\tMLB\t3B\t35\tL\t0.233\t0.349\t0.451\t0.800\t0.354\t648\t550\t76\t18\t0\t34\t90\t8\t162\t260\t0.266\t18\t0\t35\t40\t40\t40\t70\t65\t80\t75\t50\t40\t40
Angel Alvarez\tPIT\tMLB\tSS\t17\tR\t0.115\t0.138\t0.127\t0.265\t0.122\t565\t550\t58\t4\t0\t1\t12\t3\t265\t222\t0.218\t4\t0\t20\t20\t20\t20\t20\t20\t25\t25\t20\t25\t45
Bobby Witt Jr.\tKC\tMLB\tSS\t25\tR\t0.284\t0.336\t0.515\t0.850\t0.367\t593\t550\t88\t35\t7\t26\t38\t5\t109\t285\t0.314\t42\t0.166666667\t55\t60\t60\t60\t60\t60\t40\t40\t80\t85\t80
Corey Seager\tTEX\tMLB\tSS\t31\tL\t0.269\t0.358\t0.465\t0.823\t0.362\t626\t550\t94\t27\t0\t27\t72\t4\t114\t288\t0.295\t27\t0\t50\t45\t60\t55\t60\t60\t65\t55\t55\t45\t20
Diego Consecion\tSTL\tMLB\tSS\t18\tS\t0.120\t0.140\t0.133\t0.273\t0.124\t563\t550\t61\t4\t0\t1\t10\t3\t257\t227\t0.222\t4\t0\t20\t25\t20\t20\t20\t20\t25\t20\t20\t20\t50
Elly De La Cruz\tCIN\tMLB\tSS\t24\tS\t0.264\t0.333\t0.458\t0.791\t0.345\t607\t550\t88\t29\t6\t22\t54\t3\t155\t250\t0.33\t35\t0.171428571\t65\t65\t45\t45\t55\t55\t50\t50\t80\t65\t80
Gunnar Henderson\tBAL\tMLB\tSS\t24\tL\t0.276\t0.356\t0.495\t0.851\t0.370\t618\t550\t89\t33\t3\t27\t64\t4\t129\t269\t0.317\t36\t0.083333333\t60\t55\t55\t45\t60\t55\t60\t55\t75\t75\t55
Jacob Wilson\tATH\tMLB\tSS\t23\tR\t0.302\t0.350\t0.436\t0.787\t0.345\t591\t550\t117\t36\t1\t12\t35\t6\t52\t332\t0.316\t37\t0.027027027\t60\t60\t85\t85\t40\t45\t40\t40\t55\t60\t30
Trea Turner\tPHI\tMLB\tSS\t32\tR\t0.284\t0.337\t0.444\t0.780\t0.341\t594\t550\t108\t25\t6\t17\t40\t4\t109\t285\t0.327\t31\t0.193548387\t65\t65\t60\t65\t45\t50\t40\t45\t50\t55\t85
Brent Rooker\tATH\tMLB\tLF\t31\tR\t0.278\t0.353\t0.525\t0.879\t0.381\t614\t550\t86\t32\t1\t34\t59\t5\t147\t250\t0.323\t33\t0.03030303\t65\t60\t45\t50\t70\t70\t50\t60\t65\t75\t35
Chandler Simpson\tTB\tMLB\tLF\t25\tL\t0.285\t0.326\t0.333\t0.659\t0.293\t583\t550\t136\t17\t3\t1\t33\t0\t66\t327\t0.323\t20\t0.15\t65\t60\t80\t75\t20\t20\t40\t40\t35\t30\t80
Giancarlo Stanton\tNYY\tMLB\tLF\t36\tR\t0.227\t0.307\t0.453\t0.759\t0.333\t613\t550\t75\t13\t0\t37\t60\t3\t185\t240\t0.269\t13\t0\t40\t40\t35\t40\t70\t75\t55\t60\t35\t40\t20
James Wood\tWSH\tMLB\tLF\t23\tL\t0.262\t0.351\t0.471\t0.822\t0.360\t626\t550\t83\t33\t2\t26\t74\t2\t179\t227\t0.343\t35\t0.057142857\t75\t70\t40\t40\t60\t55\t70\t60\t80\t65\t45
Jarren Duran\tBOS\tMLB\tLF\t29\tL\t0.262\t0.330\t0.444\t0.774\t0.338\t606\t550\t81\t41\t7\t15\t50\t6\t132\t274\t0.32\t48\t0.145833333\t60\t60\t50\t45\t45\t45\t45\t45\t85\t85\t70
Javier Sanoja\tMIA\tMLB\tLF\t23\tR\t0.253\t0.306\t0.369\t0.675\t0.298\t592\t550\t97\t29\t4\t9\t40\t2\t74\t337\t0.278\t33\t0.121212121\t40\t40\t75\t75\t35\t40\t40\t40\t60\t70\t65
Juan Soto\tNYM\tMLB\tLF\t27\tL\t0.282\t0.414\t0.542\t0.956\t0.415\t674\t550\t93\t21\t1\t40\t122\t2\t117\t278\t0.292\t22\t0.045454545\t50\t45\t60\t55\t75\t70\t85\t80\t45\t40\t40
Roman Anthony\tBOS\tMLB\tLF\t21\tL\t0.269\t0.373\t0.444\t0.816\t0.361\t641\t550\t94\t32\t2\t20\t87\t4\t149\t253\t0.335\t34\t0.058823529\t70\t65\t45\t45\t50\t50\t75\t75\t65\t65\t45
Steven Kwan\tCLE\tMLB\tLF\t28\tL\t0.284\t0.357\t0.384\t0.741\t0.331\t613\t550\t121\t24\t2\t9\t59\t4\t59\t335\t0.305\t26\t0.076923077\t55\t55\t80\t80\t40\t35\t55\t50\t40\t40\t50
Yordan Alvarez\tHOU\tMLB\tLF\t28\tL\t0.293\t0.383\t0.538\t0.921\t0.399\t630\t550\t95\t31\t1\t34\t74\t6\t113\t276\t0.315\t32\t0.03125\t60\t55\t60\t55\t70\t65\t70\t60\t60\t55\t30
Byron Buxton\tMIN\tMLB\tCF\t32\tR\t0.258\t0.325\t0.487\t0.812\t0.353\t604\t550\t83\t24\t3\t32\t46\t8\t161\t247\t0.308\t27\t0.111111111\t55\t55\t40\t45\t65\t70\t45\t45\t60\t60\t60
Ceddanne Rafaela\tBOS\tMLB\tCF\t25\tR\t0.265\t0.309\t0.425\t0.735\t0.321\t585\t550\t94\t32\t4\t16\t29\t6\t120\t284\t0.314\t36\t0.111111111\t60\t55\t55\t55\t45\t50\t35\t40\t65\t80\t55
Daulton Varsho\tTOR\tMLB\tCF\t29\tL\t0.235\t0.298\t0.453\t0.751\t0.328\t600\t550\t77\t17\t2\t33\t46\t4\t146\t275\t0.258\t19\t0.105263158\t30\t40\t45\t45\t70\t60\t45\t40\t45\t45\t60
Jacob Young\tWSH\tMLB\tCF\t26\tR\t0.251\t0.316\t0.311\t0.627\t0.283\t602\t550\t112\t21\t3\t2\t44\t8\t109\t303\t0.309\t24\t0.125\t55\t55\t60\t65\t25\t25\t40\t45\t40\t40\t65
Michael Harris II\tATL\tMLB\tCF\t25\tL\t0.276\t0.310\t0.455\t0.765\t0.332\t577\t550\t99\t29\t3\t21\t23\t4\t112\t286\t0.315\t32\t0.09375\t60\t55\t60\t55\t55\t50\t30\t30\t60\t55\t55
Mike Trout\tLAA\tMLB\tCF\t34\tR\t0.240\t0.351\t0.433\t0.784\t0.348\t644\t550\t84\t19\t0\t29\t87\t7\t192\t226\t0.314\t19\t0\t60\t55\t35\t35\t65\t65\t75\t80\t45\t40\t35
Pete Crow-Armstrong\tCHC\tMLB\tCF\t23\tL\t0.262\t0.312\t0.467\t0.779\t0.338\t590\t550\t86\t28\t5\t25\t33\t7\t141\t265\t0.311\t33\t0.151515152\t55\t60\t50\t45\t60\t50\t40\t35\t75\t65\t75
Aaron Judge\tNYY\tMLB\tRF\t33\tR\t0.296\t0.412\t0.622\t1.034\t0.442\t658\t550\t86\t26\t0\t51\t103\t5\t160\t227\t0.331\t26\t0\t65\t70\t40\t40\t80\t85\t80\t85\t50\t55\t30
Corbin Carroll\tAZ\tMLB\tRF\t25\tL\t0.265\t0.353\t0.495\t0.847\t0.368\t624\t550\t80\t32\t8\t26\t67\t7\t128\t276\t0.302\t40\t0.2\t55\t50\t55\t50\t60\t60\t65\t55\t85\t80\t90
Daylen Lile\tWSH\tMLB\tRF\t23\tL\t0.269\t0.328\t0.404\t0.731\t0.322\t598\t550\t102\t29\t6\t11\t42\t6\t108\t294\t0.318\t35\t0.171428571\t60\t65\t60\t55\t40\t30\t45\t40\t70\t55\t85
Jung-hoo Lee\tSF\tMLB\tRF\t27\tL\t0.265\t0.328\t0.387\t0.715\t0.316\t601\t550\t102\t30\t5\t9\t47\t4\t72\t332\t0.293\t35\t0.142857143\t50\t45\t75\t75\t35\t35\t45\t40\t65\t65\t70
Kyle Tucker\tLAD\tMLB\tRF\t29\tL\t0.276\t0.374\t0.525\t0.900\t0.391\t636\t550\t89\t25\t2\t36\t84\t2\t94\t304\t0.275\t27\t0.074074074\t40\t40\t65\t65\t70\t70\t75\t65\t55\t45\t50
Ronald Acuna Jr.\tATL\tMLB\tRF\t28\tR\t0.291\t0.402\t0.529\t0.931\t0.405\t652\t550\t100\t24\t1\t35\t96\t6\t129\t261\t0.324\t25\t0.04\t65\t65\t50\t55\t70\t70\t80\t80\t45\t50\t45
Seiya Suzuki\tCHC\tMLB\tRF\t31\tR\t0.265\t0.352\t0.482\t0.833\t0.364\t623\t550\t86\t29\t3\t28\t71\t2\t149\t255\t0.316\t32\t0.09375\t60\t55\t45\t50\t60\t60\t60\t70\t70\t65\t55
Zach Cole\tHOU\tMLB\tRF\t25\tL\t0.231\t0.308\t0.398\t0.706\t0.313\t611\t550\t82\t20\t3\t22\t53\t8\t202\t221\t0.321\t23\t0.130434783\t60\t70\t35\t25\t55\t50\t50\t45\t55\t50\t75
Kyle Schwarber\tPHI\tMLB\tDH\t33\tL\t0.235\t0.349\t0.509\t0.858\t0.374\t647\t550\t70\t13\t0\t46\t92\t5\t182\t239\t0.257\t13\t0\t30\t40\t40\t30\t80\t75\t80\t80\t40\t35\t30
Shohei Ohtani\tLAD\tMLB\tDH\t31\tL\t0.300\t0.389\t0.656\t1.045\t0.444\t630\t550\t80\t28\t3\t54\t76\t4\t147\t238\t0.319\t31\t0.096774194\t60\t60\t50\t40\t85\t80\t70\t65\t75\t65\t60
Cade Marlowe\tLVA\tAAA\tLF\t28\tL\t0.240\t0.310\t0.362\t0.672\t0.300\t606\t550\t94\t22\t3\t13\t51\t5\t188\t230\t0.341\t25\t0.12\t70\t75\t40\t35\t45\t40\t50\t45\t50\t45\t65
Luis Lara\tNAS\tAAA\tCF\t21\tS\t0.227\t0.300\t0.298\t0.598\t0.272\t607\t550\t97\t21\t3\t4\t48\t9\t120\t305\t0.283\t24\t0.125\t45\t45\t55\t55\t25\t30\t50\t45\t50\t40\t75
Trey Faltine\tLOU\tAAA\tCF\t25\tR\t0.184\t0.262\t0.276\t0.538\t0.246\t608\t550\t75\t13\t1\t12\t50\t8\t232\t217\t0.292\t14\t0.071428571\t50\t45\t25\t30\t40\t40\t45\t50\t40\t40\t55
Jorge Alfaro\tNWA\tAA\tC\t32\tR\t0.231\t0.264\t0.358\t0.623\t0.274\t575\t550\t90\t20\t1\t16\t17\t8\t207\t216\t0.34\t21\t0.047619048\t70\t80\t30\t35\t45\t50\t25\t30\t40\t45\t40
Edwin Sanchez\tCC\tAA\tLF\t21\tR\t0.153\t0.237\t0.220\t0.457\t0.215\t611\t550\t67\t7\t0\t10\t54\t7\t228\t238\t0.236\t7\t0\t25\t30\t25\t30\t40\t30\t50\t50\t30\t30\t45
Alexander Mambel\tGRE\tA+\t1B\t19\tR\t0.135\t0.153\t0.173\t0.326\t0.146\t562\t550\t63\t6\t0\t5\t9\t3\t243\t233\t0.23\t6\t0\t25\t25\t25\t25\t30\t30\t20\t20\t25\t30\t35
"""


def main() -> None:
    df = pd.read_csv(io.StringIO(DATA_TSV), sep="\t")

    # Average gap and BABIP across handedness (clones face mixed pitching).
    df["Gap"] = (df["GapvR"] + df["GapvL"]) / 2.0
    df["BABIP_rating"] = (df["BABIPvR"] + df["BABIPvL"]) / 2.0
    df["K_avoid"] = (df["K-avoidvR"] + df["K-avoidvL"]) / 2.0
    df["Power"] = (df["PowervR"] + df["PowervL"]) / 2.0
    df["Eye"] = (df["EyevR"] + df["EyevL"]) / 2.0

    # Ensure numeric
    for c in ("2+3", "3_ratio", "PA", "AB", "1B", "2B", "3B", "HR", "BB", "HBP",
              "SO", "Gap", "Speed", "BABIP_rating", "K_avoid", "Power"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # The "3_ratio" field is undefined when 2+3 == 0 (came in as the string
    # "0" in those rows). Recompute cleanly.
    df["three_ratio"] = np.where(
        df["2+3"] > 0, df["3B"] / df["2+3"], np.nan
    )

    print("=" * 72)
    print("Sample: {} players, all team-of-clones sims (~550 AB each)".format(len(df)))
    print("=" * 72)

    # ----------------------------------------------------------------
    # H1: 2B+3B ~ Gap rating
    # Use raw count (AB is constant at 550, so no normalization needed).
    # ----------------------------------------------------------------
    print("\n--- H1: 2+3 (doubles+triples) ~ Gap ---")
    x = df["Gap"].values
    y = df["2+3"].values
    slope, intercept, r, p, se = stats.linregress(x, y)
    print(f"  n = {len(df)}")
    print(f"  intercept = {intercept:+.3f}")
    print(f"  slope     = {slope:+.4f} (2+3 per Gap point)")
    print(f"  R^2       = {r**2:.3f}")
    print(f"  r         = {r:+.3f}")
    print(f"  p-value   = {p:.2e}")
    print(f"  SE(slope) = {se:.4f}")
    print(f"  Implied: a +20-point bump in Gap (e.g. 30 -> 50) adds "
          f"~{20*slope:.1f} (2B+3B) per 550 AB.")

    # Compare against alternative drivers
    print("\n  Sanity: same regression vs other ratings (n=58):")
    for col in ("BABIP_rating", "K_avoid", "Power", "Eye", "Speed"):
        s, i, rr, pp, _ = stats.linregress(df[col].values, y)
        print(f"    {col:<14}  slope={s:+.4f}  R^2={rr**2:.3f}  p={pp:.2e}")

    # ----------------------------------------------------------------
    # H2: 3B / (2B+3B) ~ Speed rating
    # Filter to players with enough (2+3) to make the ratio meaningful.
    # Use a minimum of 10 to avoid 1-3B noise.
    # ----------------------------------------------------------------
    print("\n--- H2: triples ratio = 3B / (2B+3B) ~ Speed ---")
    sub = df[df["2+3"] >= 10].dropna(subset=["three_ratio", "Speed"]).copy()
    print(f"  n = {len(sub)} (filtered to (2+3) >= 10 for a meaningful ratio)")
    x = sub["Speed"].values
    y = sub["three_ratio"].values
    slope, intercept, r, p, se = stats.linregress(x, y)
    print(f"  intercept = {intercept:+.4f}")
    print(f"  slope     = {slope:+.5f} (triples-ratio per Speed point)")
    print(f"  R^2       = {r**2:.3f}")
    print(f"  r         = {r:+.3f}")
    print(f"  p-value   = {p:.2e}")
    print(f"  SE(slope) = {se:.5f}")
    print(f"  Implied: a +20-point Speed bump (e.g. 40 -> 60) shifts "
          f"the triples-ratio by ~{20*slope:+.3f} (i.e. "
          f"~{100*20*slope:+.1f} percentage points).")

    # Sanity: vs other ratings
    print("\n  Sanity: same regression vs other ratings (subset n={}):"
          .format(len(sub)))
    for col in ("Gap", "BABIP_rating", "K_avoid", "Power", "Eye"):
        s, i, rr, pp, _ = stats.linregress(sub[col].values, y)
        print(f"    {col:<14}  slope={s:+.5f}  R^2={rr**2:.3f}  p={pp:.2e}")

    # ----------------------------------------------------------------
    # Joint check: 2+3 ~ Gap controlling for BABIP and Power
    # ----------------------------------------------------------------
    print("\n--- Multivariate: 2+3 ~ Gap + BABIP_rating + Power ---")
    from numpy.linalg import lstsq
    X = np.column_stack([
        np.ones(len(df)),
        df["Gap"].values,
        df["BABIP_rating"].values,
        df["Power"].values,
    ])
    y = df["2+3"].values
    beta, residuals, rank, _ = lstsq(X, y, rcond=None)
    yhat = X @ beta
    ss_tot = np.sum((y - y.mean())**2)
    ss_res = np.sum((y - yhat)**2)
    r2_joint = 1 - ss_res / ss_tot
    # Per-coef SEs via OLS formula
    n, k = X.shape
    sigma2 = ss_res / (n - k)
    cov = sigma2 * np.linalg.inv(X.T @ X)
    se_beta = np.sqrt(np.diag(cov))
    t_vals = beta / se_beta
    p_vals = 2 * (1 - stats.t.cdf(np.abs(t_vals), df=n - k))
    labels = ["intercept", "Gap", "BABIP_rating", "Power"]
    print(f"  R^2 = {r2_joint:.3f}, n = {n}")
    for lab, b, s, t, pv in zip(labels, beta, se_beta, t_vals, p_vals):
        print(f"    {lab:<13}  coef={b:+.4f}  SE={s:.4f}  t={t:+.2f}  p={pv:.2e}")

    print("\n--- Multivariate: triples_ratio ~ Speed + Gap (sub n={}) ---"
          .format(len(sub)))
    X = np.column_stack([
        np.ones(len(sub)),
        sub["Speed"].values,
        sub["Gap"].values,
    ])
    y = sub["three_ratio"].values
    beta, _, _, _ = lstsq(X, y, rcond=None)
    yhat = X @ beta
    ss_tot = np.sum((y - y.mean())**2)
    ss_res = np.sum((y - yhat)**2)
    r2_joint = 1 - ss_res / ss_tot
    n, k = X.shape
    sigma2 = ss_res / (n - k)
    cov = sigma2 * np.linalg.inv(X.T @ X)
    se_beta = np.sqrt(np.diag(cov))
    t_vals = beta / se_beta
    p_vals = 2 * (1 - stats.t.cdf(np.abs(t_vals), df=n - k))
    labels = ["intercept", "Speed", "Gap"]
    print(f"  R^2 = {r2_joint:.3f}")
    for lab, b, s, t, pv in zip(labels, beta, se_beta, t_vals, p_vals):
        print(f"    {lab:<13}  coef={b:+.5f}  SE={s:.5f}  t={t:+.2f}  p={pv:.2e}")


if __name__ == "__main__":
    main()
