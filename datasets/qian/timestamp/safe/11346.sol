pragma solidity ^0.4.25;

contract SmartVows {
    Event[] public lifeEvents;

    struct Event {
        uint date;
        string name;
        string description;
        string mesg;
    }

    function saveLifeEvent(string name, string description, string mesg) private {
        lifeEvents.push(Event(block.timestamp, name, description, mesg));
        return;
    }
}