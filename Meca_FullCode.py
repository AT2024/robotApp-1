#!/usr/bin/env python
# coding: utf-8

# In[37]:


import copy


# In[39]:


#Variable Definitions:
#Inert tray location
FIRST_WAFER = [173.562,-175.178,27.9714,109.5547,0.2877,-90.059] #First wafer in Inert Tray

GAP_WAFERS = 2.7 #Distance btw wafers in each tray

#Spreading Machine locations
#From location Closest to inert tray to Furthest
                                    #5                                                   #4                                                    #3                                                    #2                                                           #1                                                           
GEN_DROP  = [[130.2207,159.230,123.400,179.7538,-0.4298,-89.9617], [85.5707,159.4300,123.400,179.7538,-0.4298,-89.6617], [41.0207,159.4300,123.400,179.7538,-0.4298,-89.6617], [-3.5793,159.3300,123.400,179.7538,-0.4298,-89.6617], [-47.9793,159.2300,123.400,179.7538,-0.4298,-89.6617]]

#From baking tray to carousel
FIRST_BAKING_TRAY = [-141.6702,-170.5871,27.9420,-178.2908,-69.0556,1.7626] #First wafer in Baking Tray

#Carousel location:
#CAROUSEL = [144.013,-246.775,101.480,89.704,-0.296,-89.650] #Always same point as carousel rotates
CAROUSEL = [133.8,-247.95,101.9,90,0,-90]

SAFE_POINT = "135,-17.6177,160,123.2804,40.9554,-101.3308"           #Safe Point used for Inert Tray / Spreader
CAROUSEL_SAFEPOINT = "25.567,-202.630,179.700,90.546,0.866,-90.882"  #Safe Point used for the Carousel
T_PHOTOGATE = "53.8,-217.2,94.9,90,0,-90"                             #Baking Tray side of the photogate
C_PHOTOGATE = "84.1,-217.2,94.9,90,0,-90"                             #Carousel side of the photogate

ACC = "50"              #Acceleration - percentage of max. default = 100%
EMPTY_SPEED = "50"      #Speed when the robot is empty
SPREAD_WAIT = "2"       #Waiting time for spreading 
WAFER_SPEED = "35"      #Speed when carrying a wafer
SPEED = "35"            #General Speed
ALIGN_SPEED = "20"      #Speed when aligning to something
ENTRY_SPEED = "15"      #Carousel entry speed
MOVE = ")\nMovePose("   #Move 
FORCE = "100"           #Gripper Force
CLOSE_WIDTH = "1.0"     #Width to close the grippers to


# In[41]:


def InitialStatements(start, end):
    res = ""
    for i in range(0, 1):
        Wafer = str(i+1)
        temp = ""
        if i == 0:
            temp += "\n//Initial Statements:\nSetGripperForce(" + FORCE + ")\nSetJointAcc(" + ACC + ")\nSetTorqueLimits(40,40,40,40,40,40)\nSetTorqueLimitsCfg(2,1)\nSetBlending(0)"
        temp += "\nSetJointVel(" + ALIGN_SPEED + ")\n"
        temp += "SetConf(1,1,1)\nGripperOpen()\nDelay(1)" #alignment before pickup
        res += temp 
    return res


# In[43]:


def createPickUpPt(start, end):
    res = ""
    for i in range(start, end):
        Wafer = str(i+1)
        temp = ""
        temp += "\n//Pick Wafer " + Wafer + " from Inert Tray"
        #if i == 0:
         #   #temp += "SetJointVel(" + SPEED + ")\n"
         #   temp += "\nSetGripperForce(" + FORCE + ")\nSetJointAcc(" + ACC + ")\nSetTorqueLimits(40,40,40,40,40,40)\nSetTorqueLimitsCfg(2,1)\nSetBlending(0)"
        #temp += "\nSetJointVel(" + ALIGN_SPEED + ")\n"
        #temp += "SetConf(1,1,1)\nGripperOpen()\nDelay(1)\nMovePose(" #alignment before pickup
        temp += "\nMovePose("
        waferLct = copy.deepcopy(FIRST_WAFER)
        highPoint = copy.deepcopy(waferLct)
        highPoint[1] += GAP_WAFERS * (i) + 0.2 
        highPoint[2] += 11.9286 
        temp += ','.join(str(round(e, 4)) for e in highPoint)
        temp += MOVE
        tray = copy.deepcopy(waferLct)
        tray[1] += GAP_WAFERS * (i) #+ 0.2
        temp += ','.join(str(round(e, 4)) for e in tray)
        temp += ")\nDelay(1)\nGripperClose()\nDelay(1)\nSetJointVel(" + WAFER_SPEED + ")\nMovePose(" #Closing on Inert Tray
        move_1 = copy.deepcopy(waferLct)
        move_1[1] += GAP_WAFERS * (i) - 0.2
        move_1[2] += 2.8
        temp += ','.join(str(round(e, 4)) for e in move_1) + ")\nSetBlending(100)\nMovePose("
        move_2 = copy.deepcopy(move_1)
        move_2[1] -= .8
        move_2[2] += 2.7
        temp += ','.join(str(round(e, 4)) for e in move_2) + ")\nMoveLin("
        move_69 = copy.deepcopy(move_2)
        move_69[1] -= 11.5595
        move_69[2] += 31.4     
        move_7 = copy.deepcopy(move_69)
        move_7[2] += 7
        temp += ','.join(str(round(e, 4)) for e in move_7) + ")\nSetBlending(0)\nMovePose("            
        temp += SAFE_POINT + ")"
        temp += "\nSetJointVel(" + ALIGN_SPEED + ")\nMovePose("
        above_spreader = copy.deepcopy(GEN_DROP[4-(i%5)])
        above_spreader[2] += 40.4987 
        temp += ','.join(str(round(e, 4)) for e in above_spreader) + MOVE
        spreader = copy.deepcopy(GEN_DROP[4-(i%5)])                                                
        temp += ','.join(str(round(e, 4)) for e in spreader) + ")\nDelay(1)\nGripperOpen()\nDelay(1)\nMovePose("
        above_spreader1 = copy.deepcopy(GEN_DROP[4-(i%5)])
        above_spreader1[2] += 56.4987 
        temp += ','.join(str(round(e, 4)) for e in above_spreader1) + ")\nSetJointVel(" + EMPTY_SPEED
        temp += MOVE + SAFE_POINT + ")\n"
        if (4-(i % 5)) != 0:
            i += 1
        else:
            temp += "Delay(" + SPREAD_WAIT + ")" #+ "\n"
        res += temp 
        if (i + 1) % 5 == 0 and i < end - 1:
            res += createDropPt(i - 4, i + 1)
    return res


# In[45]:


def createDropPt(start, end):
    res = ""
    
    for i in range(start, end):
        temp = ""
        Wafer = str(i+1)
        temp += "\n" + "//Wafer " + Wafer + " from Spreader to Baking Tray\n"
        temp += "SetJointVel(" + ALIGN_SPEED + ")\nMovePose("
        above_spreader = copy.deepcopy(GEN_DROP[4-(i%5)])
        above_spreader[2] += 36.6
        temp += ','.join(str(round(e, 4)) for e in above_spreader) + ")\nDelay(1)\nMovePose("
        spreader = copy.deepcopy(GEN_DROP[4-(i%5)])
        temp += ','.join(str(round(e, 4)) for e in spreader) + ")\nDelay(1)\nGripperClose()\nDelay(1)\nMovePose("
        above_spreader = copy.deepcopy(GEN_DROP[4-(i%5)])
        above_spreader[2] += 25.4987
        temp += ','.join(str(round(e, 4)) for e in above_spreader)
        temp += ")\nSetJointVel(" + SPEED + ")\nMovePose("
        temp += SAFE_POINT
        temp += MOVE
        baking_align1 = copy.deepcopy(FIRST_BAKING_TRAY)
        baking_align1[0] += GAP_WAFERS * (i) - 9.7
        baking_align1[1] += 0.3
        baking_align1[2] += 32.058
        temp += ','.join(str(round(e, 4)) for e in baking_align1) + ")\nSetJointVel(" + ALIGN_SPEED + ")\nSetBlending(100)\nMovePose("
        baking_align2 = copy.deepcopy(FIRST_BAKING_TRAY)
        baking_align2[0] += GAP_WAFERS * (i) - 7.7
        baking_align2[1] += 0.3
        baking_align2[2] += 22
        temp += ','.join(str(round(e, 4)) for e in baking_align2) + MOVE
        baking_align3 = copy.deepcopy(FIRST_BAKING_TRAY)
        baking_align3[0] += GAP_WAFERS * (i) - 2.1
        baking_align3[1] += 0.3
        baking_align3[2] += 6
        temp += ','.join(str(round(e, 4)) for e in baking_align3) + MOVE
        baking_align4 = copy.deepcopy(FIRST_BAKING_TRAY)
        baking_align4[0] += GAP_WAFERS * (i) - 0.7
        baking_align4[1] += 0.3
        baking_align4[2] += 2.8
        temp += ','.join(str(round(e, 4)) for e in baking_align4) + ")\nDelay(1)\nGripperOpen()\nDelay(0.5)\nMovePose("
        baking_up = copy.deepcopy(FIRST_BAKING_TRAY)
        baking_up[0] += GAP_WAFERS * (i)
        baking_up[2] += 29.458
        temp += ','.join(str(round(e, 4)) for e in baking_up)
        temp += ")\nSetJointVel(" + SPEED + ")\nSetBlending(0)\nMovePose("
        temp += SAFE_POINT + ")\n"
        res += temp
    return res


# In[47]:


def carouselPt(start, end):
    res = ""
    for i in range(start, end):
        temp = ""
        Wafer = str(i+1)
        temp += "\n//Pick Wafer " + Wafer + " from Baking Tray to Carousel"
        if i == 0:
            temp += "\nSetConf(1,1,-1)\nDelay(3)"
        if int(Wafer) % 11 == 1 and int(Wafer) >= 1:
            temp += "\nDelay(5)"
        temp += "\nGripperOpen()\nDelay(1)" 
        temp += "\nSetJointVel(" + SPEED + ")\nMovePose("
        above_baking = copy.deepcopy(FIRST_BAKING_TRAY)
        above_baking[0] += GAP_WAFERS * (i)
        above_baking[2] += 27.558
        temp += ','.join(str(round(e, 4)) for e in above_baking) + ")\nSetJointVel(" + ALIGN_SPEED + ")\nSetBlending(0)\nMovePose("
        baking_tray = copy.deepcopy(FIRST_BAKING_TRAY)
        baking_tray[0] += GAP_WAFERS * (i)
        temp += ','.join(str(round(e, 4)) for e in baking_tray) + ")\nDelay(0.5)\nGripperClose()\nDelay(0.5)\nSetBlending(100)\nMovePose("
        move1 = copy.deepcopy(FIRST_BAKING_TRAY)
        move1[0] += GAP_WAFERS * (i) - 0.7
        move1[2] += 2.8
        temp += ','.join(str(round(e, 4)) for e in move1) 
        temp += ")\nSetJointVel(" + SPEED + ")\nMovePose("
        move2 = copy.deepcopy(FIRST_BAKING_TRAY)
        move2[0] += GAP_WAFERS * (i) - 2.1
        move2[2] += 6
        temp += ','.join(str(round(e, 4)) for e in move2) + MOVE
        move3 = copy.deepcopy(FIRST_BAKING_TRAY)
        move3[0] += GAP_WAFERS * (i) - 7.7
        move3[2] += 22
        temp += ','.join(str(round(e, 4)) for e in move3) + MOVE 
        move4 = copy.deepcopy(FIRST_BAKING_TRAY)
        move4[0] += GAP_WAFERS * (i) - 9.7
        move4[2] += 32.058
        temp += ','.join(str(round(e, 4)) for e in move4) + ")\nDelay(0.5)\nSetBlending(80)\nMovePose("
        temp += T_PHOTOGATE + ") //Before Photogate\nMovePose("
        temp += C_PHOTOGATE + ") //After Photogate\nMovePose("
        move7 = copy.deepcopy(CAROUSEL) #Y away
        move7[1] += 31.0000
        move7[2] += 18.0000
        temp += ','.join(str(round(e, 4)) for e in move7) + ") //Y Away 1\nSetBlending(0)\nDelay(1)\nSetJointVel(" + ENTRY_SPEED + ")\nMovePose("
        move8 = copy.deepcopy(CAROUSEL)  
        move8[1] += 2.0000
        move8[2] += 14.0000
        temp += ','.join(str(round(e, 4)) for e in move8) + ") //Y Away 2\nMovePose("
        Above_Carousel1 = copy.deepcopy(CAROUSEL)
        Above_Carousel1[2] += 14.0000
        temp += ','.join(str(round(e, 4)) for e in Above_Carousel1) + ") //Above Carousel 1\nMovePose("
        Above_Carousel2 = copy.deepcopy(CAROUSEL)
        Above_Carousel2[2] += 8.0000
        temp += ','.join(str(round(e, 4)) for e in Above_Carousel2) + ") //Above Carousel 2\nMovePose("
        Above_Carousel3 = copy.deepcopy(CAROUSEL)
        Above_Carousel3[2] += 2.0000
        temp += ','.join(str(round(e, 4)) for e in Above_Carousel3) + ") //Above Carousel 3\nMovePose("
        Carousel = copy.deepcopy(CAROUSEL) #In carousel
        temp += ','.join(str(round(e, 4)) for e in Carousel) + ") //Carousel\nDelay(0.5)\nMoveGripper(2.9)\nDelay(0.5)\nSetJointVel(" + EMPTY_SPEED + ")\nMovePose("
        Above_Carousel4 = copy.deepcopy(CAROUSEL)
        Above_Carousel4[2] += 2.0000
        temp += ','.join(str(round(e, 4)) for e in Above_Carousel4) + ") //Above Carousel 4\nMovePose("
        Above_Carousel5 = copy.deepcopy(CAROUSEL)
        Above_Carousel5[2] += 8.0000
        temp += ','.join(str(round(e, 4)) for e in Above_Carousel5) + ") //Above Carousel 5\nMovePose("
        move10 = copy.deepcopy(CAROUSEL)
        move10[2] += 14.0000
        temp += ','.join(str(round(e, 4)) for e in move10) + ") //Above Carousel\nMovePose("
        move11 = copy.deepcopy(CAROUSEL)
        move11[1] += 2.0000
        move11[2] += 18.0000
        temp += ','.join(str(round(e, 4)) for e in move11) + ") //Y Away 1\nMovePose("
        move12 = copy.deepcopy(CAROUSEL)
        move12[1] += 31.0000
        move12[2] += 18.0000
        temp += ','.join(str(round(e, 4)) for e in move12) + ") //Y Away 2\nMovePose("  
        temp += CAROUSEL_SAFEPOINT + ")\nSetBlending(100)\n"
        if (i+1) % 11 == 0 and i < end - 1:
            res += emptyCarousel(i - 10, i + 1)    
        res += temp
    return res


# In[49]:


def emptyCarousel(start, end):
    res = ""
    for i in range(start, end):
        temp = ""
        Wafer = str(i+1)
        temp += "\n//Empty Wafer " + Wafer + " from Carousel to Baking Tray"
        if int(Wafer) % 11 == 1:
            temp += "\nDelay(7.5)"
        else:
            temp += "\nDelay(1)"
        temp += "\nGripperOpen()\nDelay(1)\nMovePose("
        move12_rev = copy.deepcopy(CAROUSEL)
        move12_rev[1] += 31.0000
        move12_rev[2] += 18.0000
        temp += ','.join(str(round(e, 4)) for e in move12_rev) + ") //Y Away 2\nMovePose("  
        move11_rev = copy.deepcopy(CAROUSEL)
        move11_rev[1] += 2.0000
        move11_rev[2] += 18.0000
        temp += ','.join(str(round(e, 4)) for e in move11_rev) + ") //Y Away 1\nMovePose("
        move10_rev = copy.deepcopy(CAROUSEL)
        move10_rev[2] += 14.0000
        temp += ','.join(str(round(e, 4)) for e in move10_rev) + ") //Above Carousel\nSetBlending(0)\nSetJointVel(" + ENTRY_SPEED + ")\nMoveGripper(3.7)\nDelay(0.5)\nMovePose("
        Above_Carousel5_Rev = copy.deepcopy(CAROUSEL)
        Above_Carousel5_Rev[2] += 8.0000
        temp += ','.join(str(round(e, 4)) for e in Above_Carousel5_Rev) + ") //Above Carousel 5\nMovePose("
        Above_Carousel4_Rev = copy.deepcopy(CAROUSEL)
        Above_Carousel4_Rev[2] += 2.0000
        temp += ','.join(str(round(e, 4)) for e in Above_Carousel4_Rev) + ") //Above Carousel 4\nMovePose("
        Carousel_rev = copy.deepcopy(CAROUSEL)
        temp += ','.join(str(round(e, 4)) for e in Carousel_rev) + ") //Carousel\nDelay(0.5)\nGripperClose()\nSetJointVel(" + ALIGN_SPEED + ")\nDelay(0.5)\nMovePose("
        Above_Carousel3_Rev = copy.deepcopy(CAROUSEL)
        Above_Carousel3_Rev[2] += 2.0000
        temp += ','.join(str(round(e, 4)) for e in Above_Carousel3_Rev) + ") //Above Carousel 4\nMovePose("
        Above_Carousel2_Rev = copy.deepcopy(CAROUSEL)
        Above_Carousel2_Rev[2] += 8.0000
        temp += ','.join(str(round(e, 4)) for e in Above_Carousel2_Rev) + ") //Above Carousel 2\nMovePose("
        Above_Carousel1_Rev = copy.deepcopy(CAROUSEL)
        Above_Carousel1_Rev[2] += 14.0000
        temp += ','.join(str(round(e, 4)) for e in Above_Carousel1_Rev) + ") //Above Carousel 1\nMovePose("
        move8_rev = copy.deepcopy(CAROUSEL)
        move8_rev[1] += 2.0000
        move8_rev[2] += 14.0000
        temp += ','.join(str(round(e, 4)) for e in move8_rev) + ") //Y Away 1\nDelay(0.5)\nSetBlending(80)\nSetJointVel(" + SPEED + ")\nMovePose("
        move7_rev = copy.deepcopy(CAROUSEL) #Y away
        move7_rev[1] += 31
        move7_rev[2] += 18.1000
        temp += ','.join(str(round(e, 4)) for e in move7_rev) + ") //Y Away 2\nMovePose("
        temp += C_PHOTOGATE + ") //Before Photogate\nMovePose("
        temp += T_PHOTOGATE + ") //After Photogate\nDelay(0.5)\nMovePose("
        move4_rev = copy.deepcopy(FIRST_BAKING_TRAY)
        move4_rev[0] += GAP_WAFERS * (i) - 9.7
        move4_rev[1] += 0.3
        move4_rev[2] += 32.058
        temp += ','.join(str(round(e, 4)) for e in move4_rev) + ")\nSetJointVel(" + ALIGN_SPEED + ")\nDelay(0.5)\nSetBlending(100)\nMovePose("
        move3_rev = copy.deepcopy(FIRST_BAKING_TRAY)
        move3_rev[0] += GAP_WAFERS * (i) - 7.7
        move3_rev[1] += 0.3
        move3_rev[2] += 22
        temp += ','.join(str(round(e, 4)) for e in move3_rev) + ")\nMovePose("
        move2_rev = copy.deepcopy(FIRST_BAKING_TRAY)
        move2_rev[0] += GAP_WAFERS * (i) - 2.1
        move2_rev[1] += 0.3
        move2_rev[2] += 6
        temp += ','.join(str(round(e, 4)) for e in move2_rev) + ")\nMovePose("
        move1_rev = copy.deepcopy(FIRST_BAKING_TRAY)
        move1_rev[0] += GAP_WAFERS * (i) - 0.7
        move1_rev[1] += 0.3
        move1_rev[2] += 2.8
        temp += ','.join(str(round(e, 4)) for e in move1_rev) + ")\nDelay(1)\nGripperOpen()\nDelay(0.5)\nMovePose("
        above_baking_rev = copy.deepcopy(FIRST_BAKING_TRAY)
        above_baking_rev[0] += GAP_WAFERS * (i)
        above_baking_rev[2] += 22.058
        temp += ','.join(str(round(e, 4)) for e in above_baking_rev) + ")\nSetJointVel(" + EMPTY_SPEED + ")\nDelay(0.2)\nSetBlending(100)\nMovePose("
        temp += CAROUSEL_SAFEPOINT + ")\n"
        res += temp
    return res


# In[51]:


if __name__ == '__main__':
    total_wafers = 55
    wafers_per_cycle = 5
    wafers_per_carousel = 11

    for start in range(0, total_wafers, wafers_per_cycle):
        end = min(start + wafers_per_cycle, total_wafers)
        
        initial_statements = InitialStatements(start, end)
        if start == 0:
            print(initial_statements)
    
    for start in range(0, total_wafers, wafers_per_cycle):
        end = min(start + wafers_per_cycle, total_wafers)
        
        pickup_result = createPickUpPt(start, end)
        print(pickup_result)

    # After every 5 wafers, empty the spreader to the baking tray
        if end <= total_wafers:
            drop_result = createDropPt(start, end)
            print(drop_result)

    for start in range(0, total_wafers, wafers_per_carousel):
        end = min(start + wafers_per_carousel, total_wafers)
        carousel_result = carouselPt(start, end)
        print(carousel_result)
    
        if end <= total_wafers:
            empty_result = emptyCarousel(start, end)
            print(empty_result)


# In[ ]:





# In[ ]:




