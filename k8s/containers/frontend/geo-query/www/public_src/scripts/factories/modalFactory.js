function makeDialog (type, configs) {
  return {
    clickOutsideToClose: configs.clickOutsideToClose ? configs.clickOutsideToClose : true,

    templateUrl: 'views/components/modalTemplate.html',

    controller: function DialogController($scope, $sce, $mdDialog, $cookies) {
      $scope.configs = configs;
      $scope.type = type;
      $scope.hideMsg = false;
      $scope.showCheckbox = !!configs.hideCookie;

      if (configs.content || configs.textContent) {
        var content = configs.content ? configs.content : '<p>' + configs.textContent + '</p>';
        $scope.trustedContent = $sce.trustAsHtml(content);
      }



      $scope.cancelDialog = function() {
        if (configs.hideCookie) { $cookies.put(configs.hideCookie, $scope.hideMsg); }

        $mdDialog.cancel();
      };
      $scope.closeDialog = function() {
        if (configs.hideCookie) { $cookies.put(configs.hideCookie, $scope.hideMsg); }

        $mdDialog.hide();
      };
    }
  };
}
angular.module('aiddataDET')
  .factory('modalFactory', function($log, $mdDialog) {
    return {
      dialog: function (configs) {
        return makeDialog('dialog', configs);
      },
      confirm: function (configs) {
        return makeDialog('confirm', configs);
      },
      alert: function (configs) {
        return makeDialog('alert', {
          title: configs.message,
          name: configs.name
        });
      }
    };
  });
