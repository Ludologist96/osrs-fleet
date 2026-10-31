"""Offline walk through the Tutorial Island SCRIPT with instructions OCR'd in a live run
(run 2, RhettCaan125, in order): the scripted step must match what the island asked.

Run: DISPLAY=:99 python tests/test_tutorial_script.py  (see test_tutorial_rules.py)."""
import os, sys, types
sys.modules.setdefault("mouseinfo", types.ModuleType("mouseinfo"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bots.tutorial_island as T  # noqa: E402

RUN = [  # (OCR text, step it must give)
    ("Getting started TOhen you're ready to get started, cHck on the Guide. He is indicated by a flashing yellow", "talk"),
    ("Sectings IDnenu Please cHck on the flashing spanner {con found at the bottom of Y0uF scFeen- display your settings menu", "tab"),
    ("Sectings Tnenu On the s(de panel, Ou see a variety of game setfngs You can also the all settings button ta available settfngs Galk tothe Guide to continue.", "talk"),
    ("(Doving OTL It's time to meet first fnstructotr. Go continue, all 400 need is cHck on the door. It's indicated by a flashing yellow arrow.", "door"),
    ("Follow the path to find the Survival Instructor. Click on the ground or minimap bomove.", "walk to npc"),
    ("You've been gven an (tem Go view the ftem you've been given, youTl need to fnventory- Go do so, cHck on 5 flashing backpack icon", "tab"),
    ("Inventory Ghis is your inventory: You can view all of your ftems here, including the net just been gven. ft to catch shtfmp.", "fishing"),
    ("You've some experience Click onthe flashing bar graph icon near the fnventory button to menu,", "tab"),
    ("SGiIs and Experience On this menu you can view your can be Ieweled up by earning rr Speak tothe survival expert to continue:", "talk"),
    ("It's time to cooR 4youv shtfmp. HoweweT, 40 require a fire to do that which means you need some Iogs- You can)cut down trees", "woodcutting"),
    ("Fivemaking 92ow that you have some Togs, it's time to a fire. First, on the tnderbox in your fnventory-", "firemaking"),
    ("CooRin 92ow it's dme 9, so, on the shtfmp Tn your on with 8. shrfm highK hted, cKck ona fire to cook them.", "cook shrimp"),
    ("(Doving OTL TOcIl done you've just cooked Your first meall Speak tothe survival expert if you Want a ¥ecap, otherwise YOu GAn..moVe on: Click onthe gate", "go on"),
    ("(Doving OTL Follow the you get tog the door with the ycIlow AYFOW above ft. at on the doof to open ft:", "door"),
    ("Cooking Galk tothe chef to learn the more advanced Aspects of Cooking such as combfnfng ingredients!", "talk"),
    ("(Daking dough Ghis is the base for Any make dough you must mix flour with do so, click on the flour fn your inventory:", "dough"),
    ("Cooking dough 92ow you have made the dough You can bake ft {nto some bread. Go do so just click on the {fndicated range.", "bake"),
    ("(Doving OTL baked Your ffrst Ioaf of bread. As you gaTn experience fn Cooking you wil be able other 3 Tke pies and an now use the next door to move on.", "door"),
    ("Fancy a run? TOhen navi adng the world, You can either fun of walk. Running is faster you can't run for ong", "run"),
    ("Quests to Tearn about questsf Just talk Guide to get started.", "talk"),
    ("Quest journal Click onthe flashing icon to the of your inventory:", "tab"),
    ("Quest journal Ghis is yout quest journal Iv Hots every quest fn the game: Galk tothe quest gvide again explanation on how", "talk"),
    ("(Doving OTL It's time to enter some caves. Click on the to go downto the next area.", "ladder"),
    ("(Dining and Smithfn T2ext Tet's get you a weapon, OF TnoYe to can make 4youv first Don't the mining will help you: alk to", "talk"),
    ("(Dining It's quite simple really. Go mine a rock, all 40 need todo fs cHckR on Eirst up, try mining some tn.", "mine"),
    ("(Dining 92ow that you have some tin ore, you just need some COpper: Go mine a rock, all 40 need to dois cAck on ft.", "mine"),
    ("Smelting You now have some tn ofe and some You can smelt these bar. Go do so, just click on the {fndicated furnace.", "smelt"),
    ("Smelting You've made a bronze barI Speak tothe mining fnstructor and hel show you how to make ft foto a Weapon.", "talk"),
    ("Smithing a dagger Go smith youT need a hamme7 and enough metal bars to make the cd item, as well asa handy anvi.7Go start", "anvil"),
    ("Smithing a dagger 92ow you have the smithing menu you wil see a Hest of aT the things you can make. 8.4 the Sp can be mad", "smithing menu"),
    ("(Doving OTL Congratulations, you've made YOuF first weapon. 92ow it's dme to move on. Go through the pr shown by the arrow", "door"),
    ("CombPar In this area you wil find out about melee and ranged combat. Speak tothe gvide and he will tell you all about fe.", "talk"),
    ("Equipping ftems You now have access toa new on the flashing icon of aman, the one to the of 4youv backpack Icon-", "tab"),
    ("TOorn fnventory Ghis is Here YOu can. see what have equipped In the bottom eft corner, you will notice a) button with a s", "equipment stats"),
    ("Equipment Stats You can see what fterms you are wearing fn the worn fnventory tothe left of the screen, with thefr combin", "wield dagger"),
    ("E You're now holding 5 Clothes, afmour, weapons and TDnOYe a¥e equipped ike this. Iternatively, You can click dfvectIy fr", "talk"),
    ("Unequipping Go an (tem, go to your w0rn fnventory and cHck on the fteTn- Alternatively, a new ftem into the same slo will", "sword and shield"),
    ("CombBat fntetface Click onthe flashing ctossed swords fcon. to open the combat fntetface.", "tab"),
    ("CombBat fntetface Ghis fs combat here, you cam select the attack style that youT use Using different attack styles will g", "talk"),
    ("Enter the cage through the nearby and click rat. Retwrn to the Combat Instructor once the rat is dead.", "attack rat"),
    ("ell done, you've made 4Y0ouF¥ first EI Pass through the gate and talk TO the combat in.st¥uctor: He wil gve 4ou", "first kill"),
    ("9Rar ranging Before You cam. use the shortbow and arrows youT need to equip them by clicking on them. Once equipped with", "bow"),
    ("(Doving OTL You have completed the tasks move on, cHck on the fndicated If you need to go of what you Iearnt here, just t", "ladder"),
    ("Banking Ghis fs the Bank of Gieinor, where YOu sto¥e all most bank just click on the fndicated booth.", "bank booth"),
    ("Rankin Ghis is Your can store 8p here for safekee ing: Go depostt something from just cHck on ft can withdraw things fn t", "poll booth"),
    ("(Doving OTL Polls are run periodically to Tet the School community vote on how the game shouId shouldn't - change: TOhen", "door"),
    ("Account (Danagemeng Ghe gvide here will cell you aIl.abour Just click on him to hear what got to say:", "talk"),
    ("Account (Danagemeng Click onthe flashing fcon to Account (Danagemeng IDenu:", "tab"),
    ("Account (Danagemeng Ghis is 4Y0ouF¥ Account (Danagemeng where 4ou C8Ty control various Aspects of 4Y0ouF¥ Galk TO the Acc", "talk"),
    ("(Doving OTL Continue through the next doot.", "door"),
    ("Exit the door and follow the path to the chapel. Once there: speak to Brother Brace.", "door"),
    ("Prayer menu Click onthe flashing fcon to open the Prayer TDeTLUx", "tab"),
    ("Prayer Galk with Brother Brace and hel cell 4ou about Prayers:", "talk"),
    ("Your finaI instructor You're almost finished on tutorial island. Pass through the door to find the path Ieading to your f", "door"),
    ("Your finaI instructor Follow the path to the house, where you wil be shown how to cast TOhen you get there, just talk wit", "walk to npc"),
    ("Open Open up the magic fntetface by clicking on the flashing Icon-", "tab"),
    ("(Dagic Ghis is your magic fntetface. XR of YouF spells can be found here. Ghe Hist fis Currently ffitered to only show th", "talk"),
    ("(Dagic casting You now have some runes. Q spells require runes to cast them. Cook for the spell magic on this spell to se", "magic: cast"),
    ("Go the mafnlandJ You're neatly finished with the need now is move onto the speak with 8 magic In.stfUCtO¥ to continue:", "mainland"),
    ("Go the mainlandJ You're neatly finished with the you need now is move onto the mainland. Cast YouF Home spell tobe taken to Cumbridge-", "mainland"),
]


class FakeBot(T.BotExecutor):
    def __init__(self):
        self.log = T.get_logger("test")
        self.same = self.walks = 0
        self.idx = None
        self.cfg = T.BotConfig()

    def _load_idx(self):
        return None

    def _save_idx(self):
        pass


def run(start=0):
    b, bad = FakeBot(), 0
    for i, (text, want) in enumerate(RUN[start:], start):
        name, _h, canon = b._script_step(text.lower(), new_text=True)
        if name != want:
            bad += 1
            print(f"FAIL #{i + 1}: want {want!r} got {name!r} (script {b.idx + 1}: {canon[:50]}) | {text[:60]}")
    return bad


bad = run(0) + run(30) + run(50)  # from the start, and accounts starting in the middle
# an account starting at any instruction must land on that step (same step name at least)
for i, (text, want) in enumerate(RUN):
    b = FakeBot()
    name, _h, _c = b._script_step(text.lower(), new_text=True)
    if name != want:
        bad += 1
        print(f"FAIL start at #{i + 1}: want {want!r} got {name!r} (script {b.idx + 1})")
print("ok" if not bad else f"{bad} failures")
sys.exit(1 if bad else 0)
