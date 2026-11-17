using Celeste;
using Monocle;
using Microsoft.Xna.Framework;

namespace CelesteAgentBridge;

// Virtual inputs are swapped only while the agent owns a bounded sequence.
public sealed class InputController {
    public static readonly HashSet<string> Allowed = new() { "left","right","up","down","jump","dash","grab" };
    sealed class Button : VirtualButton.Node {
        public bool Held, Previous;
        public override bool Check => Held;
        public override bool Pressed => Held && !Previous;
        public override bool Released => !Held && Previous;
    }
    sealed class AimNode : VirtualJoystick.Node {
        public Vector2 Direction;
        public override Vector2 Value => Direction;
    }
    readonly Button jump=new(), dash=new(), grab=new();
    readonly AimNode aim=new();
    VirtualButton? oldJump,oldDash,oldGrab;
    VirtualJoystick? oldAim;
    VirtualIntegerAxis? oldX,oldY;
    public void Apply(IEnumerable<string> buttons) {
        if(oldJump==null) {
            oldJump=Input.Jump; oldDash=Input.Dash; oldGrab=Input.Grab;
            oldAim=Input.Aim; oldX=Input.MoveX; oldY=Input.MoveY;
            Input.Jump=new VirtualButton(0, jump); Input.Dash=new VirtualButton(0,dash); Input.Grab=new VirtualButton(0,grab);
            Input.Aim=new VirtualJoystick(true,aim); Input.MoveX=new VirtualIntegerAxis(); Input.MoveY=new VirtualIntegerAxis();
        }
        var held=buttons.ToHashSet();
        Set(jump,held.Contains("jump")); Set(dash,held.Contains("dash")); Set(grab,held.Contains("grab"));
        int x=(held.Contains("right")?1:0)-(held.Contains("left")?1:0);
        int y=(held.Contains("down")?1:0)-(held.Contains("up")?1:0);
        Input.MoveX.Value=x; Input.MoveY.Value=y; aim.Direction=new Vector2(x,y);
        Input.Jump.Update(); Input.Dash.Update(); Input.Grab.Update(); Input.Aim.Update(); Input.UpdateGrab();
    }
    static void Set(Button button,bool held) { button.Previous=button.Held; button.Held=held; }
    public void Release() {
        if(oldJump==null) return;
        Input.Jump.Deregister(); Input.Dash.Deregister(); Input.Grab.Deregister(); Input.Aim.Deregister(); Input.MoveX.Deregister(); Input.MoveY.Deregister();
        Input.Jump=oldJump; Input.Dash=oldDash!; Input.Grab=oldGrab!; Input.Aim=oldAim!; Input.MoveX=oldX!; Input.MoveY=oldY!;
        oldJump=null;
        jump.Held=jump.Previous=dash.Held=dash.Previous=grab.Held=grab.Previous=false;
        Input.ResetGrab();
    }
}
