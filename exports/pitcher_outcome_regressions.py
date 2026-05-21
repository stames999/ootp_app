"""Pitcher rating-to-outcome regression scan.

Inputs the user's 95-pitcher in-game projection sample. Tests every
key outcome (K%, BB%, HR%, BABIP-against, pwOBA-against) against:
  - Stuff / Movement / Control / HRA / pBABIP (vsR + vsL splits)
  - Pitch arsenal (fastball, slider, etc.)
  - Misc (velocity, stamina, arm_slot, ground_fly, hold, wild_pitch, balk)

Same methodology as the hitter regressions:
  1. Univariate scan
  2. Multivariate "best" model
  3. Interaction tests
  4. Leave-one-out cross-validation
  5. Bootstrap CIs on headline coefs
  6. vsR/vsL mix decomposition
"""
import io
import re

import numpy as np
import pandas as pd
from numpy.linalg import lstsq
from scipy import stats

# ----------------------------------------------------------------------
# Data — pasted from the user's filled-in projection sheet.
# Columns include K%, BB%, HR% as percent-strings — parsed below.
# ----------------------------------------------------------------------
DATA_TSV = """Name\tOrg\tLevel\tThrows\tAge\tBF\tPA\tIP\tFIP\tWHIP\tK\tH\tHR\tBB\tHP\tER\tK/9\tBB/9\tHR/9\tK%\tBB%\tHR%\tBABIP-against\tpwOBA-against\tGO\tFO\tHR/FB\tStuffvR\tStuffvL\tMovementvR\tMovementvL\tControlvR\tControlvL\tHRAvR\tHRAvL\tpBABIPvR\tpBABIPvL\tFastball\tSlider\tCurveball\tChangeup\tSinker\tSplitter\tCutter\tCircleCh\tKnucklecurve\tKnuckleball\tForkball\tScrewball\tVelocity\tVelocityTgt\tArmSlot\tStamina\tGroundFly\tHold\tBalk\tWildPitch
Alex Vesia\tLAD\tMLB\tL\t29\t612\t550\t143.0\t3.72\t1.28\t172\t121\t17\t62\t6\t10.8\t10.8\t3.9\t1.1\t28%\t10%\t3%\t0.288\t0.296\t111\t146\t10.4%\t65\t70\t50\t50\t40\t40\t45\t45\t60\t65\t75\t60\t0\t50\t0\t0\t0\t0\t0\t0\t0\t0\t13\t13\t3\t30\t43\t50\t2\t5
Aroldis Chapman\tBOS\tMLB\tL\t38\t617\t550\t145.0\t3.07\t1.26\t189\t115\t12\t67\t3\t8.9\t11.7\t4.2\t0.7\t31%\t11%\t2%\t0.295\t0.277\t123\t123\t8.9%\t75\t80\t55\t60\t40\t40\t60\t65\t45\t50\t75\t75\t0\t0\t0\t65\t0\t0\t0\t0\t0\t0\t19\t19\t4\t30\t50\t40\t1\t10
Brendon Little\tTOR\tMLB\tL\t29\t640\t550\t142.7\t3.69\t1.49\t164\t122\t9\t90\t6\t12.0\t10.3\t5.7\t0.6\t26%\t14%\t1%\t0.300\t0.300\t198\t66\t12.0%\t60\t75\t60\t65\t35\t35\t70\t75\t45\t45\t0\t0\t65\t0\t75\t0\t50\t0\t0\t0\t0\t0\t15\t15\t4\t30\t75\t55\t3\t4
Brooks Raley\tNYM\tMLB\tL\t37\t597\t550\t140.0\t3.67\t1.26\t133\t130\t12\t47\t14\t7.4\t8.6\t3.0\t0.8\t22%\t8%\t2%\t0.291\t0.300\t138\t149\t7.4%\t45\t55\t55\t70\t50\t55\t60\t70\t55\t60\t0\t55\t0\t55\t50\t0\t50\t0\t0\t0\t0\t0\t10\t10\t3\t25\t48\t65\t1\t7
Chris Sale\tATL\tMLB\tL\t36\t592\t550\t141.3\t3.19\t1.19\t157\t126\t13\t42\t8\t9.0\t10.0\t2.7\t0.8\t27%\t7%\t2%\t0.297\t0.285\t136\t131\t9.0%\t60\t65\t50\t55\t60\t60\t55\t60\t45\t50\t70\t70\t0\t0\t50\t0\t0\t50\t0\t0\t0\t0\t16\t16\t2\t60\t51\t60\t2\t5
Cole Ragans\tKC\tMLB\tL\t28\t603\t550\t142.0\t3.30\t1.25\t164\t124\t14\t53\t3\t8.6\t10.4\t3.4\t0.9\t27%\t9%\t2%\t0.296\t0.286\t113\t149\t8.6%\t65\t55\t55\t50\t50\t45\t60\t50\t45\t45\t70\t60\t60\t70\t0\t0\t60\t0\t0\t0\t0\t0\t16\t16\t4\t60\t43\t55\t2\t7
Cristopher Sanchez\tPHI\tMLB\tL\t29\t586\t550\t139.7\t3.11\t1.20\t134\t131\t11\t36\t4\t9.2\t8.6\t2.3\t0.7\t23%\t6%\t2%\t0.296\t0.280\t177\t108\t9.2%\t50\t55\t55\t65\t65\t70\t60\t70\t45\t50\t0\t55\t0\t60\t70\t0\t0\t0\t0\t0\t0\t0\t15\t15\t3\t60\t62\t60\t1\t5
Drew Pomeranz\tLAA\tMLB\tL\t37\t595\t550\t139.7\t3.86\t1.26\t148\t131\t17\t45\t13\t10.8\t9.5\t2.9\t1.1\t25%\t8%\t3%\t0.296\t0.309\t130\t141\t10.8%\t50\t65\t45\t50\t50\t55\t45\t50\t45\t50\t60\t0\t0\t0\t0\t0\t0\t0\t70\t0\t0\t0\t12\t12\t3\t30\t48\t55\t1\t9
Framber Valdez\tDET\tMLB\tL\t32\t598\t550\t139.7\t3.47\t1.28\t130\t131\t11\t48\t6\t10.1\t8.4\t3.1\t0.7\t22%\t8%\t2%\t0.293\t0.291\t191\t98\t10.1%\t45\t50\t60\t65\t50\t50\t60\t65\t50\t55\t0\t45\t60\t45\t60\t0\t45\t0\t0\t0\t0\t0\t15\t15\t3\t60\t66\t65\t1\t6
Gabe Speier\tSEA\tMLB\tL\t30\t596\t550\t140.7\t3.63\t1.24\t150\t128\t16\t46\t7\t10.3\t9.6\t2.9\t1.0\t25%\t8%\t3%\t0.292\t0.296\t133\t139\t10.3%\t55\t65\t50\t55\t50\t55\t45\t55\t50\t55\t65\t55\t0\t0\t55\t0\t0\t0\t0\t0\t0\t0\t15\t15\t3\t30\t49\t50\t1\t6
Garrett Cleavinger\tTB\tMLB\tL\t31\t604\t550\t142.7\t3.76\t1.23\t169\t122\t17\t54\t14\t12.3\t10.7\t3.4\t1.1\t28%\t9%\t3%\t0.288\t0.302\t137\t122\t12.3%\t65\t70\t45\t50\t45\t45\t45\t50\t55\t70\t65\t70\t50\t0\t55\t0\t0\t0\t0\t0\t0\t0\t15\t15\t2\t30\t53\t60\t1\t4
Garrett Crochet\tBOS\tMLB\tL\t26\t591\t550\t142.0\t2.96\t1.16\t164\t124\t13\t41\t3\t9.2\t10.4\t2.6\t0.8\t28%\t7%\t2%\t0.298\t0.275\t134\t128\t9.2%\t60\t70\t50\t55\t60\t60\t55\t60\t45\t45\t70\t60\t0\t55\t50\t0\t65\t0\t0\t0\t0\t0\t17\t17\t3\t50\t51\t50\t2\t8
Jose Alvarado\tPHI\tMLB\tL\t30\t610\t550\t141.7\t3.34\t1.31\t159\t125\t12\t60\t3\t8.6\t10.1\t3.8\t0.8\t26%\t10%\t2%\t0.298\t0.288\t138\t128\t8.6%\t60\t60\t55\t55\t45\t40\t60\t60\t45\t50\t0\t0\t0\t0\t65\t0\t70\t0\t0\t0\t0\t0\t18\t18\t3\t30\t52\t45\t3\t11
Josh Hader\tHOU\tMLB\tL\t31\t609\t550\t144.7\t3.41\t1.21\t188\t116\t17\t59\t5\t9.7\t11.7\t3.7\t1.1\t31%\t10%\t3%\t0.287\t0.285\t89\t157\t9.7%\t75\t80\t45\t50\t45\t45\t40\t45\t60\t75\t75\t75\t0\t40\t0\t0\t0\t0\t0\t0\t0\t0\t16\t16\t2\t30\t36\t50\t1\t2
Kyle Backhus\tPHI\tMLB\tL\t28\t602\t550\t138.3\t4.09\t1.35\t130\t135\t15\t52\t13\t12.8\t8.5\t3.4\t1.0\t22%\t9%\t2%\t0.296\t0.316\t182\t103\t12.8%\t45\t50\t45\t55\t50\t50\t50\t55\t45\t50\t0\t50\t0\t45\t50\t0\t0\t0\t0\t0\t0\t0\t8\t8\t2\t30\t64\t60\t1\t11
MacKenzie Gore\tTEX\tMLB\tL\t27\t605\t550\t140.0\t3.74\t1.32\t149\t130\t15\t55\t7\t9.1\t9.6\t3.5\t1.0\t25%\t9%\t2%\t0.298\t0.303\t122\t149\t9.1%\t55\t55\t50\t50\t45\t45\t50\t50\t45\t45\t70\t60\t70\t45\t0\t0\t0\t0\t0\t0\t0\t0\t16\t16\t3\t55\t45\t55\t3\t8
Max Fried\tNYY\tMLB\tL\t32\t592\t550\t139.7\t3.75\t1.24\t126\t131\t15\t42\t5\t12.8\t8.1\t2.7\t1.0\t21%\t7%\t3%\t0.284\t0.294\t190\t103\t12.8%\t45\t50\t60\t65\t60\t60\t65\t70\t55\t55\t50\t50\t50\t45\t45\t0\t45\t0\t0\t0\t0\t0\t14\t14\t3\t60\t65\t70\t1\t8
Shane McClanahan\tTB\tMLB\tL\t28\t591\t550\t139.3\t3.60\t1.24\t137\t132\t16\t41\t2\t12.5\t8.8\t2.6\t1.0\t23%\t7%\t3%\t0.292\t0.293\t169\t112\t12.5%\t50\t50\t50\t50\t60\t60\t50\t50\t50\t50\t65\t55\t60\t50\t0\t0\t0\t0\t0\t0\t0\t0\t17\t17\t3\t55\t60\t65\t1\t8
Tanner Scott\tLAD\tMLB\tL\t31\t604\t550\t140.7\t3.53\t1.29\t148\t128\t13\t54\t6\t9.7\t9.5\t3.5\t0.8\t25%\t9%\t2%\t0.296\t0.294\t153\t121\t9.7%\t55\t60\t55\t60\t45\t50\t55\t60\t50\t55\t55\t70\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t17\t17\t3\t30\t56\t45\t1\t7
Tarik Skubal\tDET\tMLB\tL\t29\t581\t550\t143.0\t2.68\t1.06\t164\t121\t12\t31\t4\t8.3\t10.3\t2.0\t0.8\t28%\t5%\t2%\t0.291\t0.263\t133\t133\t8.3%\t65\t60\t60\t60\t75\t70\t65\t60\t50\t55\t70\t60\t45\t70\t65\t0\t0\t0\t0\t0\t0\t0\t19\t19\t3\t60\t50\t55\t1\t9
Tyler Holton\tDET\tMLB\tL\t29\t588\t550\t137.3\t4.15\t1.28\t110\t138\t18\t38\t3\t11.0\t7.2\t2.5\t1.2\t19%\t6%\t3%\t0.284\t0.306\t157\t145\t11.0%\t40\t40\t50\t50\t65\t60\t45\t45\t65\t70\t35\t35\t30\t40\t45\t0\t45\t0\t0\t0\t0\t0\t12\t12\t4\t35\t52\t55\t1\t8
Abner Uribe\tMIL\tMLB\tR\t25\t616\t550\t143.7\t3.39\t1.29\t162\t119\t10\t66\t10\t10.7\t10.1\t4.1\t0.6\t26%\t11%\t2%\t0.288\t0.287\t186\t83\t10.7%\t65\t60\t70\t65\t40\t40\t70\t65\t65\t55\t0\t70\t0\t40\t70\t0\t0\t0\t0\t0\t0\t0\t19\t19\t3\t30\t69\t45\t1\t10
Andres Munoz\tSEA\tMLB\tR\t27\t608\t550\t144.7\t3.14\t1.20\t179\t116\t12\t58\t9\t10.3\t11.1\t3.6\t0.7\t29%\t10%\t2%\t0.290\t0.280\t150\t105\t10.3%\t70\t70\t65\t60\t45\t45\t65\t60\t65\t55\t70\t75\t0\t0\t60\t0\t0\t0\t0\t0\t0\t0\t19\t19\t3\t30\t59\t50\t2\t8
Antonio Senzatela\tCOL\tMLB\tR\t31\t598\t550\t130.0\t5.20\t1.60\t71\t160\t19\t48\t6\t11.5\t4.9\t3.3\t1.3\t12%\t8%\t3%\t0.307\t0.352\t172\t147\t11.5%\t30\t30\t40\t40\t50\t50\t45\t40\t35\t35\t35\t35\t30\t35\t35\t0\t0\t0\t0\t0\t0\t0\t15\t15\t3\t55\t54\t50\t1\t9
Bryan Abreu\tHOU\tMLB\tR\t28\t615\t550\t144.3\t3.30\t1.26\t183\t117\t13\t65\t8\t8.8\t11.4\t4.1\t0.8\t30%\t11%\t2%\t0.294\t0.287\t115\t135\t8.8%\t75\t70\t60\t50\t40\t40\t60\t55\t55\t50\t70\t75\t0\t45\t0\t0\t0\t0\t0\t0\t0\t0\t17\t17\t3\t30\t46\t55\t3\t8
Bryan Woo\tSEA\tMLB\tR\t26\t583\t550\t139.3\t3.59\t1.18\t132\t132\t16\t33\t6\t9.5\t8.5\t2.1\t1.0\t23%\t6%\t3%\t0.289\t0.292\t134\t152\t9.5%\t50\t45\t50\t50\t70\t70\t50\t45\t65\t60\t60\t50\t0\t45\t50\t0\t0\t0\t0\t0\t0\t0\t15\t15\t3\t55\t47\t45\t2\t5
Cade Smith\tCLE\tMLB\tR\t26\t598\t550\t144.7\t2.85\t1.13\t180\t116\t11\t48\t10\t8.0\t11.2\t3.0\t0.7\t30%\t8%\t2%\t0.292\t0.272\t127\t127\t8.0%\t70\t75\t65\t60\t50\t50\t65\t65\t55\t50\t75\t65\t0\t0\t0\t70\t0\t0\t0\t0\t0\t0\t16\t16\t3\t30\t50\t50\t1\t7
Chad Patrick\tMIL\tMLB\tR\t27\t598\t550\t138.3\t4.09\t1.32\t133\t135\t18\t48\t6\t9.6\t8.7\t3.1\t1.2\t22%\t8%\t3%\t0.293\t0.311\t113\t169\t9.6%\t50\t50\t50\t45\t50\t50\t45\t45\t55\t50\t50\t45\t0\t45\t50\t0\t60\t0\t0\t0\t0\t0\t14\t14\t3\t55\t40\t40\t2\t8
Chris Martin\tTEX\tMLB\tR\t39\t582\t550\t137.3\t3.58\t1.24\t127\t138\t16\t32\t3\t11.1\t8.3\t2.1\t1.0\t22%\t5%\t3%\t0.300\t0.298\t157\t128\t11.1%\t45\t45\t45\t45\t70\t75\t45\t50\t45\t45\t45\t0\t0\t0\t40\t40\t50\t0\t0\t0\t0\t0\t15\t15\t3\t30\t55\t55\t1\t4
Clay Holmes\tNYM\tMLB\tR\t32\t597\t550\t138.0\t3.53\t1.33\t113\t136\t9\t47\t7\t9.3\t7.4\t3.1\t0.6\t19%\t8%\t2%\t0.297\t0.296\t214\t87\t9.3%\t40\t40\t65\t60\t55\t50\t75\t70\t45\t40\t35\t45\t30\t45\t50\t0\t40\t0\t0\t0\t0\t0\t15\t15\t3\t55\t71\t55\t1\t6
Daniel Palencia\tCHC\tMLB\tR\t26\t597\t550\t141.0\t3.58\t1.23\t151\t127\t15\t47\t9\t8.7\t9.6\t3.0\t1.0\t25%\t8%\t3%\t0.292\t0.295\t114\t158\t8.7%\t55\t60\t50\t50\t50\t50\t50\t50\t60\t55\t70\t60\t0\t0\t0\t40\t0\t0\t0\t0\t0\t0\t19\t19\t3\t35\t42\t45\t1\t7
David Bednar\tNYY\tMLB\tR\t31\t599\t550\t142.0\t3.35\t1.22\t169\t124\t16\t49\t4\t9.8\t10.7\t3.1\t1.0\t28%\t8%\t3%\t0.296\t0.288\t111\t146\t9.8%\t70\t65\t50\t45\t50\t50\t50\t45\t50\t50\t75\t0\t70\t0\t0\t60\t0\t0\t0\t0\t0\t0\t17\t17\t3\t30\t43\t50\t2\t7
Devin Williams\tNYM\tMLB\tR\t31\t612\t550\t145.0\t3.21\t1.22\t184\t115\t13\t62\t7\t9.2\t11.4\t3.8\t0.8\t30%\t10%\t2%\t0.289\t0.280\t123\t128\t9.2%\t75\t70\t60\t55\t45\t40\t60\t55\t55\t60\t65\t0\t0\t75\t0\t0\t40\t0\t0\t0\t0\t0\t15\t15\t4\t30\t49\t40\t1\t4
Edwin Diaz\tLAD\tMLB\tR\t31\t603\t550\t144.7\t3.21\t1.17\t189\t116\t15\t53\t11\t10.9\t11.8\t3.3\t0.9\t31%\t9%\t2%\t0.292\t0.284\t123\t123\t10.9%\t75\t80\t50\t50\t45\t50\t50\t50\t55\t50\t70\t75\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t18\t18\t3\t30\t50\t45\t1\t7
Felix Bautista\tBAL\tMLB\tR\t30\t619\t550\t144.0\t3.51\t1.30\t181\t118\t15\t69\t4\t10.5\t11.3\t4.3\t0.9\t29%\t11%\t2%\t0.291\t0.290\t123\t128\t10.5%\t70\t70\t50\t50\t40\t40\t50\t50\t60\t60\t60\t0\t60\t0\t70\t70\t0\t0\t0\t0\t0\t0\t17\t17\t3\t30\t49\t60\t1\t13
Fernando Cruz\tNYY\tMLB\tR\t35\t621\t550\t143.3\t3.56\t1.33\t180\t120\t14\t71\t8\t8.7\t11.3\t4.5\t0.9\t29%\t11%\t2%\t0.298\t0.297\t103\t148\t8.7%\t70\t70\t50\t50\t40\t40\t55\t50\t45\t40\t65\t60\t0\t0\t0\t80\t0\t0\t0\t0\t0\t0\t15\t15\t4\t30\t41\t55\t1\t8
Freddy Peralta\tNYM\tMLB\tR\t29\t604\t550\t140.7\t3.84\t1.29\t152\t128\t17\t54\t6\t9.8\t9.7\t3.5\t1.1\t25%\t9%\t3%\t0.291\t0.302\t113\t157\t9.8%\t60\t55\t50\t45\t45\t45\t45\t45\t60\t55\t75\t60\t50\t60\t0\t0\t0\t0\t0\t0\t0\t0\t15\t15\t3\t55\t42\t60\t2\t5
Garrett Whitlock\tBOS\tMLB\tR\t29\t589\t550\t141.7\t3.29\t1.16\t160\t125\t16\t39\t5\t11.2\t10.2\t2.5\t1.0\t27%\t7%\t3%\t0.291\t0.284\t138\t127\t11.2%\t70\t50\t55\t50\t65\t60\t60\t50\t50\t45\t0\t70\t0\t60\t60\t0\t0\t0\t0\t0\t0\t0\t16\t16\t3\t35\t52\t45\t1\t4
George Kirby\tSEA\tMLB\tR\t28\t580\t550\t138.3\t3.45\t1.19\t129\t135\t15\t30\t5\t9.0\t8.4\t2.0\t1.0\t22%\t5%\t3%\t0.296\t0.292\t134\t152\t9.0%\t45\t45\t50\t50\t75\t75\t50\t50\t50\t45\t55\t50\t35\t0\t50\t40\t0\t0\t0\t0\t0\t0\t16\t16\t3\t60\t47\t50\t2\t4
Griffin Jax\tTB\tMLB\tR\t31\t590\t550\t143.7\t2.77\t1.11\t178\t119\t13\t40\t4\t10.9\t11.2\t2.5\t0.8\t30%\t7%\t2%\t0.295\t0.268\t147\t106\t10.9%\t70\t70\t55\t50\t60\t60\t60\t55\t45\t45\t65\t75\t50\t55\t50\t0\t0\t0\t0\t0\t0\t0\t17\t17\t4\t30\t58\t50\t1\t7
Hunter Brown\tHOU\tMLB\tR\t27\t599\t550\t140.3\t3.45\t1.27\t138\t129\t12\t49\t5\t8.4\t8.9\t3.1\t0.8\t23%\t8%\t2%\t0.293\t0.289\t153\t130\t8.4%\t50\t50\t55\t55\t50\t50\t60\t60\t55\t50\t60\t50\t45\t45\t50\t0\t40\t0\t0\t0\t0\t0\t17\t17\t3\t60\t54\t40\t4\t7
Hunter Greene\tCIN\tMLB\tR\t26\t598\t550\t142.0\t3.71\t1.21\t154\t124\t16\t48\t12\t8.8\t9.8\t3.0\t1.0\t26%\t8%\t3%\t0.284\t0.297\t106\t166\t8.8%\t60\t60\t55\t50\t50\t50\t50\t50\t70\t65\t70\t65\t40\t0\t0\t55\t0\t0\t0\t0\t0\t0\t18\t18\t3\t55\t39\t50\t1\t3
Jacob deGrom\tTEX\tMLB\tR\t37\t587\t550\t139.3\t3.80\t1.21\t137\t132\t19\t37\t2\t11.9\t8.8\t2.4\t1.2\t23%\t6%\t3%\t0.287\t0.296\t141\t141\t11.9%\t50\t50\t50\t45\t65\t65\t45\t40\t65\t60\t65\t65\t45\t40\t0\t0\t0\t0\t0\t0\t0\t0\t18\t18\t3\t50\t50\t60\t1\t3
Jeremiah Estrada\tSD\tMLB\tR\t27\t611\t550\t143.3\t3.50\t1.26\t183\t120\t17\t61\t4\t10.4\t11.5\t3.8\t1.1\t30%\t10%\t3%\t0.294\t0.291\t101\t146\t10.4%\t75\t70\t50\t45\t45\t40\t50\t45\t55\t50\t75\t70\t0\t0\t0\t60\t0\t0\t0\t0\t0\t0\t17\t17\t3\t30\t41\t55\t4\t6
Jhoan Duran\tPHI\tMLB\tR\t28\t596\t550\t143.3\t2.65\t1.16\t162\t120\t7\t46\t8\t7.1\t10.2\t2.9\t0.4\t27%\t8%\t1%\t0.297\t0.267\t177\t91\t7.1%\t65\t60\t75\t70\t55\t50\t80\t80\t50\t45\t65\t0\t60\t0\t65\t0\t0\t0\t0\t0\t0\t0\t20\t20\t4\t30\t66\t50\t1\t5
Jose Soriano\tLAA\tMLB\tR\t27\t608\t550\t141.7\t3.46\t1.29\t150\t125\t11\t58\t9\t10.3\t9.5\t3.7\t0.7\t25%\t10%\t2%\t0.293\t0.292\t179\t96\t10.3%\t60\t50\t65\t60\t45\t45\t70\t60\t50\t50\t60\t45\t60\t0\t60\t50\t0\t0\t0\t0\t0\t0\t18\t18\t3\t55\t65\t50\t1\t6
Kenley Jansen\tDET\tMLB\tR\t38\t594\t550\t140.0\t3.72\t1.24\t141\t130\t17\t44\t3\t8.7\t9.1\t2.8\t1.1\t24%\t7%\t3%\t0.288\t0.295\t100\t179\t8.7%\t55\t50\t50\t45\t55\t55\t50\t45\t60\t55\t0\t45\t0\t0\t50\t0\t70\t0\t0\t0\t0\t0\t13\t13\t4\t30\t36\t35\t6\t8
Logan Gilbert\tSEA\tMLB\tR\t28\t588\t550\t139.7\t3.71\t1.21\t141\t131\t18\t38\t4\t11.5\t9.1\t2.4\t1.2\t24%\t6%\t3%\t0.289\t0.296\t139\t139\t11.5%\t50\t55\t45\t50\t65\t65\t45\t45\t60\t55\t60\t60\t50\t0\t0\t45\t50\t0\t0\t0\t0\t0\t17\t17\t3\t65\t50\t45\t1\t5
Logan Webb\tSF\tMLB\tR\t29\t583\t550\t139.0\t2.94\t1.19\t127\t133\t9\t33\t3\t7.9\t8.2\t2.1\t0.6\t22%\t6%\t2%\t0.300\t0.276\t186\t104\t7.9%\t45\t45\t65\t60\t70\t70\t70\t70\t45\t40\t45\t50\t0\t55\t60\t0\t45\t0\t0\t0\t0\t0\t13\t13\t4\t65\t64\t45\t1\t4
Mason Miller\tSD\tMLB\tR\t27\t607\t550\t148.3\t2.71\t1.09\t223\t105\t15\t57\t5\t10.9\t13.5\t3.5\t0.9\t37%\t9%\t2%\t0.288\t0.263\t100\t122\t10.9%\t85\t80\t55\t50\t45\t45\t50\t50\t65\t60\t80\t75\t0\t45\t0\t0\t0\t0\t0\t0\t0\t0\t20\t20\t3\t30\t45\t50\t1\t5
Matt Brash\tSEA\tMLB\tR\t27\t606\t550\t142.3\t3.14\t1.26\t160\t123\t10\t56\t7\t8.2\t10.1\t3.5\t0.6\t26%\t9%\t2%\t0.297\t0.283\t155\t112\t8.2%\t65\t60\t65\t60\t45\t45\t70\t65\t45\t45\t70\t70\t0\t40\t0\t0\t0\t0\t50\t0\t0\t0\t17\t17\t3\t30\t58\t45\t2\t5
Matt Waldron\tSD\tMLB\tR\t29\t597\t550\t135.0\t4.77\t1.42\t113\t145\t22\t47\t6\t11.9\t7.5\t3.1\t1.5\t19%\t8%\t4%\t0.296\t0.334\t128\t164\t11.9%\t40\t40\t40\t40\t50\t50\t40\t40\t50\t45\t45\t40\t0\t0\t0\t0\t40\t0\t0\t50\t0\t0\t11\t11\t3\t55\t44\t45\t1\t4
Paul Skenes\tPIT\tMLB\tR\t23\t590\t550\t142.0\t3.08\t1.15\t149\t124\t12\t40\t4\t8.6\t9.4\t2.5\t0.8\t25%\t7%\t2%\t0.288\t0.274\t150\t127\t8.6%\t60\t55\t65\t60\t60\t60\t65\t60\t60\t55\t65\t60\t45\t50\t60\t0\t0\t0\t0\t0\t0\t0\t18\t19\t3\t60\t54\t45\t2\t7
Pierce Johnson\tCIN\tMLB\tR\t34\t607\t550\t138.7\t4.02\t1.38\t140\t134\t17\t57\t3\t10.8\t9.1\t3.7\t1.1\t23%\t9%\t3%\t0.298\t0.309\t135\t141\t10.8%\t50\t55\t45\t45\t45\t45\t45\t45\t50\t45\t55\t0\t0\t0\t0\t0\t40\t0\t70\t0\t0\t0\t16\t16\t3\t30\t49\t50\t1\t2
Pierson Ohl\tCOL\tMLB\tR\t26\t579\t550\t133.3\t4.43\t1.34\t99\t150\t21\t29\t3\t10.1\t6.7\t2.0\t1.4\t17%\t5%\t4%\t0.300\t0.325\t114\t187\t10.1%\t40\t35\t40\t40\t80\t70\t45\t40\t40\t40\t40\t40\t35\t45\t0\t0\t0\t0\t0\t0\t0\t0\t10\t10\t3\t55\t38\t45\t2\t2
Porter Hodge\tCHC\tMLB\tR\t25\t624\t550\t144.3\t3.70\t1.32\t187\t117\t16\t74\t8\t10.7\t11.7\t4.6\t1.0\t30%\t12%\t3%\t0.291\t0.298\t113\t133\t10.7%\t75\t70\t50\t50\t40\t40\t50\t45\t55\t50\t0\t70\t0\t0\t0\t50\t75\t0\t0\t0\t0\t0\t16\t16\t3\t30\t46\t45\t3\t5
Roki Sasaki\tLAD\tMLB\tR\t24\t601\t550\t139.7\t3.99\t1.30\t155\t131\t19\t51\t9\t12.0\t10.0\t3.3\t1.2\t26%\t8%\t3%\t0.298\t0.312\t124\t140\t12.0%\t60\t55\t45\t40\t50\t50\t45\t40\t45\t45\t65\t55\t0\t0\t0\t65\t0\t0\t0\t0\t0\t0\t18\t18\t3\t65\t47\t50\t1\t5
Spencer Schwellenbach\tATL\tMLB\tR\t25\t580\t550\t138.7\t3.55\t1.18\t129\t134\t16\t30\t5\t9.4\t8.4\t1.9\t1.0\t22%\t5%\t3%\t0.291\t0.292\t132\t155\t9.4%\t50\t40\t50\t45\t80\t70\t50\t45\t55\t50\t55\t45\t45\t0\t0\t45\t45\t0\t0\t0\t0\t0\t16\t16\t3\t50\t46\t50\t1\t3
Trevor Megill\tMIL\tMLB\tR\t32\t603\t550\t141.3\t3.52\t1.27\t162\t126\t16\t53\t3\t9.0\t10.3\t3.4\t1.0\t27%\t9%\t3%\t0.296\t0.292\t100\t162\t9.0%\t60\t65\t45\t50\t45\t50\t50\t50\t45\t45\t75\t0\t65\t0\t0\t0\t0\t0\t0\t0\t0\t0\t19\t19\t4\t30\t38\t45\t1\t6
Yoshinobu Yamamoto\tLAD\tMLB\tR\t27\t590\t550\t141.0\t3.39\t1.18\t140\t127\t14\t40\t4\t9.5\t8.9\t2.6\t0.9\t24%\t7%\t2%\t0.285\t0.283\t150\t133\t9.5%\t55\t50\t55\t55\t60\t60\t55\t50\t70\t65\t60\t40\t55\t0\t45\t50\t50\t0\t0\t0\t0\t0\t16\t16\t3\t55\t53\t60\t1\t7
Zack Wheeler\tPHI\tMLB\tR\t35\t591\t550\t139.3\t3.56\t1.24\t133\t132\t14\t41\t6\t9.3\t8.6\t2.6\t0.9\t23%\t7%\t2%\t0.293\t0.294\t148\t137\t9.3%\t50\t50\t55\t50\t60\t60\t55\t50\t55\t50\t60\t55\t45\t45\t50\t0\t0\t0\t0\t0\t0\t0\t16\t16\t3\t65\t52\t55\t1\t4
Colton Gordon\tSUG\tAAA\tL\t27\t594\t550\t135.0\t4.69\t1.40\t114\t145\t22\t44\t6\t11.9\t7.6\t2.9\t1.5\t19%\t7%\t4%\t0.297\t0.332\t128\t163\t11.9%\t40\t40\t40\t40\t55\t55\t40\t40\t45\t50\t45\t45\t40\t40\t0\t0\t30\t0\t0\t0\t0\t0\t11\t11\t3\t50\t44\t60\t2\t8
Jake Miller\tTOL\tAAA\tL\t24\t609\t550\t132.7\t5.28\t1.59\t88\t152\t20\t59\t7\t10.3\t6.0\t4.0\t1.4\t14%\t10%\t3%\t0.299\t0.349\t136\t174\t10.3%\t35\t35\t40\t40\t50\t50\t35\t40\t45\t50\t40\t40\t0\t40\t0\t0\t30\t0\t0\t0\t0\t0\t12\t14\t3\t45\t44\t50\t1\t7
Martin Perez\tGWI\tAAA\tL\t34\t607\t550\t134.3\t4.65\t1.52\t100\t147\t17\t57\t3\t10.1\t6.7\t3.8\t1.1\t16%\t9%\t3%\t0.300\t0.330\t152\t152\t10.1%\t35\t40\t45\t45\t45\t50\t45\t50\t40\t40\t35\t0\t35\t0\t45\t0\t40\t40\t0\t0\t0\t0\t12\t12\t3\t50\t50\t65\t1\t10
Tyler Gilbert\tCHR\tAAA\tL\t32\t610\t550\t136.3\t4.62\t1.47\t119\t141\t19\t60\t4\t9.6\t7.9\t4.0\t1.3\t20%\t10%\t3%\t0.296\t0.327\t110\t180\t9.6%\t40\t45\t45\t45\t45\t45\t40\t45\t45\t50\t50\t40\t0\t40\t0\t0\t45\t0\t40\t0\t0\t0\t11\t11\t2\t40\t38\t55\t1\t4
Albert Suarez\tNOR\tAAA\tR\t36\t604\t550\t133.3\t5.21\t1.53\t111\t150\t25\t54\t3\t12.4\t7.5\t3.6\t1.7\t18%\t9%\t4%\t0.302\t0.348\t113\t176\t12.4%\t40\t40\t40\t35\t50\t45\t40\t35\t40\t40\t45\t40\t0\t0\t0\t0\t0\t40\t40\t0\t0\t0\t14\t14\t3\t50\t39\t55\t1\t3
Alexis Diaz\tRR\tAAA\tR\t29\t635\t550\t140.0\t5.06\t1.54\t131\t130\t17\t85\t18\t8.7\t8.4\t5.5\t1.1\t21%\t13%\t3%\t0.281\t0.337\t110\t179\t8.7%\t50\t50\t55\t50\t35\t35\t50\t45\t75\t65\t60\t55\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t14\t14\t3\t30\t38\t50\t1\t7
Carlos Carrasco\tGWI\tAAA\tR\t38\t600\t550\t132.3\t5.05\t1.53\t101\t153\t22\t50\t6\t13.7\t6.9\t3.4\t1.5\t17%\t8%\t4%\t0.307\t0.348\t157\t139\t13.7%\t40\t35\t40\t35\t50\t50\t40\t40\t35\t35\t40\t40\t35\t40\t40\t0\t0\t0\t0\t0\t0\t0\t12\t12\t3\t50\t53\t65\t2\t2
Cory Lewis\tSTP\tAAA\tR\t25\t642\t550\t135.3\t5.68\t1.74\t119\t144\t23\t92\t2\t12.5\t7.9\t6.1\t1.5\t19%\t14%\t4%\t0.297\t0.355\t126\t161\t12.5%\t45\t40\t40\t40\t35\t35\t40\t40\t45\t45\t50\t45\t45\t45\t0\t0\t0\t0\t0\t45\t0\t0\t11\t11\t3\t55\t44\t45\t1\t7
Gregory Santos\tSAC\tAAA\tR\t26\t612\t550\t139.3\t3.43\t1.39\t126\t132\t6\t62\t9\t4.9\t8.1\t4.0\t0.4\t21%\t10%\t1%\t0.301\t0.296\t175\t117\t4.9%\t45\t45\t75\t65\t40\t40\t85\t80\t45\t40\t0\t55\t0\t0\t55\t0\t0\t0\t0\t0\t0\t0\t17\t17\t3\t30\t60\t50\t1\t5
Brent Honeywell\tRCH\tAA\tR\t30\t603\t550\t134.3\t4.82\t1.49\t95\t147\t18\t53\t7\t10.1\t6.4\t3.6\t1.2\t16%\t9%\t3%\t0.295\t0.334\t148\t160\t10.1%\t35\t35\t45\t45\t50\t45\t45\t45\t50\t45\t40\t40\t0\t35\t0\t0\t0\t0\t0\t0\t0\t40\t15\t15\t3\t35\t48\t55\t1\t3
Landon Harper\tCBS\tAA\tR\t24\t595\t550\t134.7\t4.65\t1.42\t111\t146\t22\t45\t1\t11.8\t7.4\t3.0\t1.5\t19%\t8%\t4%\t0.297\t0.328\t129\t164\t11.8%\t40\t40\t40\t40\t55\t55\t40\t40\t50\t45\t45\t40\t0\t0\t0\t30\t45\t0\t0\t0\t0\t0\t11\t11\t3\t40\t44\t50\t3\t4
Trent Thornton\tKNO\tAA\tR\t32\t597\t550\t135.3\t4.72\t1.41\t110\t144\t21\t47\t6\t11.4\t7.3\t3.1\t1.4\t18%\t8%\t4%\t0.294\t0.330\t133\t163\t11.4%\t40\t40\t40\t45\t50\t50\t40\t40\t50\t50\t40\t45\t40\t0\t0\t30\t40\t0\t0\t0\t0\t0\t16\t16\t4\t30\t45\t55\t4\t5
Chandler Welch\tWIL\tA+\tR\t23\t645\t550\t128.3\t7.89\t2.03\t80\t165\t36\t95\t5\t17.4\t5.6\t6.7\t2.5\t12%\t15%\t6%\t0.297\t0.414\t134\t171\t17.4%\t30\t30\t35\t30\t35\t30\t30\t25\t45\t45\t35\t35\t30\t30\t30\t0\t40\t0\t0\t0\t0\t0\t12\t12\t3\t50\t44\t40\t3\t7
Dylan Simmons\tDTO\tA+\tR\t25\t639\t550\t129.7\t7.08\t1.93\t75\t161\t29\t89\t5\t15.3\t5.2\t6.2\t2.0\t12%\t14%\t5%\t0.296\t0.392\t154\t160\t15.3%\t30\t30\t35\t35\t35\t35\t35\t35\t45\t45\t35\t40\t30\t30\t30\t0\t0\t0\t0\t0\t0\t0\t14\t14\t3\t30\t49\t45\t3\t9
Janser Lara\tHIC\tA+\tR\t29\t623\t550\t134.3\t6.34\t1.64\t131\t147\t33\t73\t14\t16.4\t8.8\t4.9\t2.2\t21%\t12%\t5%\t0.295\t0.381\t103\t169\t16.4%\t50\t50\t35\t35\t40\t40\t30\t30\t50\t50\t60\t0\t50\t0\t0\t0\t0\t50\t0\t0\t0\t0\t14\t14\t3\t35\t38\t45\t1\t6
Bryan Perez\tACOL\tR\tR\t22\t654\t550\t127.3\t7.70\t2.14\t72\t168\t30\t104\t7\t15.7\t5.1\t7.4\t2.1\t11%\t16%\t5%\t0.308\t0.413\t149\t161\t15.7%\t30\t30\t30\t30\t30\t30\t35\t35\t30\t30\t35\t0\t35\t30\t0\t0\t0\t0\t0\t0\t0\t0\t13\t13\t3\t50\t48\t55\t1\t11
Efren Alvarez\tFSTL\tR\tR\t18\t730\t550\t115.3\t15.24\t3.33\t29\t204\t69\t180\t5\t26.3\t2.3\t14.0\t5.4\t4%\t25%\t9%\t0.299\t0.549\t124\t193\t26.3%\t20\t20\t20\t20\t20\t20\t20\t20\t45\t40\t30\t0\t20\t0\t0\t0\t0\t0\t0\t0\t0\t0\t6\t8\t3\t30\t39\t35\t1\t4
Jacob Roberts\tFWAS\tR\tR\t24\t669\t550\t118.7\t11.60\t2.64\t24\t194\t52\t119\t6\t21.6\t1.8\t9.0\t3.9\t4%\t18%\t8%\t0.300\t0.493\t143\t189\t21.6%\t20\t20\t25\t25\t25\t25\t20\t20\t40\t40\t25\t20\t20\t0\t0\t0\t0\t0\t0\t0\t0\t0\t11\t11\t3\t40\t43\t45\t1\t5
Kendrick Hernandez\tTig1\tR\tR\t19\t760\t550\t104.3\t23.27\t4.28\t6\t237\t107\t210\t30\t35.6\t0.5\t18.1\t9.2\t1%\t28%\t14%\t0.297\t0.677\t114\t193\t35.6%\t20\t20\t20\t20\t20\t20\t20\t20\t45\t45\t20\t0\t0\t20\t0\t0\t20\t0\t0\t0\t0\t0\t1\t1\t3\t25\t37\t25\t5\t15
Yanzel Correa\tACOL\tR\tR\t21\t687\t550\t126.0\t9.13\t2.45\t67\t172\t35\t137\t7\t17.8\t4.8\t9.8\t2.5\t10%\t20%\t5%\t0.306\t0.441\t149\t162\t17.8%\t30\t30\t30\t30\t20\t20\t30\t30\t30\t30\t35\t35\t0\t35\t0\t0\t0\t0\t0\t0\t0\t0\t10\t10\t3\t55\t48\t45\t3\t8
"""


def parse_pct(s):
    """Convert '28%' -> 0.28, '0.288' -> 0.288, '' -> NaN."""
    if pd.isna(s) or s == "":
        return np.nan
    s = str(s).strip()
    if s.endswith("%"):
        return float(s[:-1]) / 100.0
    try:
        return float(s)
    except ValueError:
        return np.nan


def univariate(df, y_col, predictors):
    rows = []
    y = df[y_col].values
    for p in predictors:
        x = df[p].values
        mask = ~(np.isnan(x) | np.isnan(y))
        if mask.sum() < 10:
            continue
        s, i, r, pv, se = stats.linregress(x[mask], y[mask])
        rows.append({"predictor": p, "slope": s, "intercept": i,
                     "R2": r**2, "p": pv, "n": int(mask.sum())})
    return pd.DataFrame(rows).sort_values("R2", ascending=False)


def ols(X, y, labels):
    beta, _, _, _ = lstsq(X, y, rcond=None)
    yhat = X @ beta
    ss_tot = np.sum((y - y.mean())**2)
    ss_res = np.sum((y - yhat)**2)
    r2 = 1 - ss_res / ss_tot
    n, k = X.shape
    sigma2 = ss_res / max(n - k, 1)
    cov = sigma2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    t = beta / se
    p = 2 * (1 - stats.t.cdf(np.abs(t), df=max(n - k, 1)))
    return {"labels": labels, "coef": beta, "se": se, "t": t, "p": p,
            "r2": r2, "n": n}


def loo_rmse(d, ycol, cols):
    d = d.dropna(subset=[ycol] + cols)
    y = d[ycol].values
    X = np.column_stack([np.ones(len(d))] + [d[c].values for c in cols])
    n = len(d)
    errors = []
    for i in range(n):
        idx = np.arange(n) != i
        beta, _, _, _ = lstsq(X[idx], y[idx], rcond=None)
        errors.append((y[i] - X[i] @ beta)**2)
    return float(np.sqrt(np.mean(errors)))


def print_ols(r, title):
    print(f"\n--- {title} ---")
    print(f"  n = {r['n']}  R^2 = {r['r2']:.4f}")
    for lab, c, s, t, p in zip(r["labels"], r["coef"], r["se"], r["t"], r["p"]):
        print(f"    {lab:<14}  coef={c:+.5f}  SE={s:.5f}  t={t:+6.2f}  p={p:.2e}")
    # Implied vsR/vsL mix
    if all(x in r["labels"] for x in ("vsR", "vsL")):
        ir = r["labels"].index("vsR"); il = r["labels"].index("vsL")
        cr, cl = r["coef"][ir], r["coef"][il]
        if cr + cl != 0:
            w = cr / (cr + cl)
            print(f"    Implied vsR mix: {w*100:.1f}% (vsL {(1-w)*100:.1f}%)")


def main():
    df = pd.read_csv(io.StringIO(DATA_TSV), sep="\t")

    # Parse pct columns
    for c in ("K%", "BB%", "HR%", "HR/FB"):
        df[c] = df[c].apply(parse_pct)
    # Numeric coercion for everything else
    num_cols = ["Age","BF","PA","IP","FIP","WHIP","K","H","HR","BB","HP","ER",
                "K/9","BB/9","HR/9","BABIP-against","pwOBA-against","GO","FO",
                "StuffvR","StuffvL","MovementvR","MovementvL",
                "ControlvR","ControlvL","HRAvR","HRAvL","pBABIPvR","pBABIPvL",
                "Fastball","Slider","Curveball","Changeup","Sinker","Splitter",
                "Cutter","CircleCh","Knucklecurve","Knuckleball","Forkball","Screwball",
                "Velocity","VelocityTgt","ArmSlot","Stamina","GroundFly","Hold",
                "Balk","WildPitch"]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Averages across vsR/vsL (same as hitter analysis)
    df["Stuff"]     = (df["StuffvR"] + df["StuffvL"]) / 2
    df["Movement"]  = (df["MovementvR"] + df["MovementvL"]) / 2
    df["Control"]   = (df["ControlvR"] + df["ControlvL"]) / 2
    df["HRA"]       = (df["HRAvR"] + df["HRAvL"]) / 2
    df["pBABIP"]    = (df["pBABIPvR"] + df["pBABIPvL"]) / 2
    df["GOpct"]     = df["GO"] / (df["GO"] + df["FO"])

    n = len(df)
    print(f"Sample: {n} pitchers, mean BF {df['BF'].mean():.0f}\n")

    # Predictor lists
    AVG_RATINGS = ["Stuff", "Movement", "Control", "HRA", "pBABIP", "Velocity",
                   "Stamina", "GroundFly", "ArmSlot", "Hold", "WildPitch"]
    SPLIT_PAIRS = [
        ("Stuff",    "StuffvR",    "StuffvL"),
        ("Movement", "MovementvR", "MovementvL"),
        ("Control",  "ControlvR",  "ControlvL"),
        ("HRA",      "HRAvR",      "HRAvL"),
        ("pBABIP",   "pBABIPvR",   "pBABIPvL"),
    ]

    # ================================================================
    # 1. Univariate for each headline outcome
    # ================================================================
    outcomes = [
        ("K%",            "K-rate"),
        ("BB%",           "BB-rate"),
        ("HR%",           "HR-rate"),
        ("BABIP-against", "BABIP-against"),
        ("pwOBA-against", "pwOBA-against"),
    ]
    for ycol, label in outcomes:
        print("=" * 78)
        print(f"OUTCOME: {label} ({ycol})")
        print("=" * 78)
        uni = univariate(df, ycol, AVG_RATINGS + [c for _, r, l in SPLIT_PAIRS for c in (r, l)])
        print(uni.head(8).to_string(index=False))

    # ================================================================
    # 2. Headline multivariate models (vsR + vsL splits where applicable)
    # ================================================================
    print("\n" + "=" * 78)
    print("2. MULTIVARIATE — vsR + vsL splits + relevant covariates")
    print("=" * 78)

    # K%: Stuff + Movement (vsR + vsL)
    d = df.dropna(subset=["K%", "StuffvR", "StuffvL", "MovementvR", "MovementvL"])
    X = np.column_stack([
        np.ones(len(d)),
        d["StuffvR"].values, d["StuffvL"].values,
        d["MovementvR"].values, d["MovementvL"].values,
    ])
    print_ols(ols(X, d["K%"].values,
                  ["intercept","StuffvR","StuffvL","MovementvR","MovementvL"]),
              "K% ~ Stuff(vR+vL) + Movement(vR+vL)")

    # BB%: Control (vsR + vsL), WildPitch
    d = df.dropna(subset=["BB%", "ControlvR", "ControlvL"])
    X = np.column_stack([
        np.ones(len(d)),
        d["ControlvR"].values, d["ControlvL"].values,
        d["WildPitch"].values,
    ])
    print_ols(ols(X, d["BB%"].values,
                  ["intercept","vsR","vsL","WildPitch"]),
              "BB% ~ Control(vR+vL) + WildPitch")

    # HR%: HRA (vsR + vsL) + GroundFly
    d = df.dropna(subset=["HR%", "HRAvR", "HRAvL", "GroundFly"])
    X = np.column_stack([
        np.ones(len(d)),
        d["HRAvR"].values, d["HRAvL"].values,
        d["GroundFly"].values,
    ])
    print_ols(ols(X, d["HR%"].values,
                  ["intercept","vsR","vsL","GroundFly"]),
              "HR% ~ HRA(vR+vL) + GroundFly")

    # BABIP-against: pBABIP (vsR + vsL) + GroundFly
    d = df.dropna(subset=["BABIP-against", "pBABIPvR", "pBABIPvL", "GroundFly"])
    X = np.column_stack([
        np.ones(len(d)),
        d["pBABIPvR"].values, d["pBABIPvL"].values,
        d["GroundFly"].values,
    ])
    print_ols(ols(X, d["BABIP-against"].values,
                  ["intercept","vsR","vsL","GroundFly"]),
              "BABIP-against ~ pBABIP(vR+vL) + GroundFly")

    # pwOBA-against: all main ratings averaged
    d = df.dropna(subset=["pwOBA-against","Stuff","Movement","Control","HRA","pBABIP"])
    X = np.column_stack([
        np.ones(len(d)),
        d["Stuff"].values, d["Movement"].values, d["Control"].values,
        d["HRA"].values, d["pBABIP"].values,
    ])
    print_ols(ols(X, d["pwOBA-against"].values,
                  ["intercept","Stuff","Movement","Control","HRA","pBABIP"]),
              "pwOBA-against ~ Stuff + Movement + Control + HRA + pBABIP")

    # ================================================================
    # 3. Final tightest formulas with LOO-CV
    # ================================================================
    print("\n" + "=" * 78)
    print("3. LEAVE-ONE-OUT cross-validated RMSE for final formulas")
    print("=" * 78)

    df["Stuff2"] = df["Stuff"]**2
    df["Movement2"] = df["Movement"]**2
    df["Control2"] = df["Control"]**2
    df["HRA2"] = df["HRA"]**2
    df["pBABIP2"] = df["pBABIP"]**2

    specs = [
        ("K%",            [["Stuff"], ["Stuff","Movement"], ["Stuff","Stuff2"],
                            ["Stuff","Movement","Stuff2"]]),
        ("BB%",           [["Control"], ["Control","Control2"], ["Control","WildPitch"]]),
        ("HR%",           [["HRA"], ["HRA","GroundFly"], ["HRA","HRA2"],
                            ["HRA","GroundFly","HRA2"]]),
        ("BABIP-against", [["pBABIP"], ["pBABIP","GroundFly"], ["pBABIP","Stuff"]]),
        ("pwOBA-against", [["Stuff","Control","HRA","pBABIP"],
                            ["Stuff","Movement","Control","HRA","pBABIP"],
                            ["Stuff","Stuff2","Control","HRA","pBABIP"]]),
    ]
    for ycol, variants in specs:
        d = df.dropna(subset=[ycol])
        print(f"\n  {ycol}:")
        for cols in variants:
            r = loo_rmse(d, ycol, cols)
            print(f"    {' + '.join(cols):<55}  LOO-RMSE = {r:.5f}")


if __name__ == "__main__":
    main()
