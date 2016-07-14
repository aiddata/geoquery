angular.module('aiddataDET')
.controller('OptionsCtrl', function($scope, $rootScope, $log) {
  $scope.dataset = {};

  $scope.options = [
    {
      name: "Extract Options",
      type: "checkbox",
      loc: "options.extract_types",
      data: []
    },
    {
      name: "Resources",
      type: "checkbox",
      loc: "resources",
      data: []
    },
    {
      name: "Metadata",
      type: "paragraph"
    }
  ];

  $scope.toggleOption = function (isChecked, option) {
    console.log(isChecked, option);
  };

  $rootScope.$on('dataset:selected', function(e, data) {
    $scope.dataset = data;
    console.log(data);

    if (data.type !== 'raster') { return; }
    _.each($scope.options, function(option) {
      if (option.loc) {
        option.data = _.chain($scope.dataset)
          .get(option.loc)
          .map(function(choice) {
            return _.isString(choice) ? { name: choice } : choice;
          })
          .value();
      }
    });
  });

  {

  $scope.data = {};
  $scope.data.cb1 = true;
  $scope.data.cb2 = false;
  $scope.data.cb3 = false;
  $scope.data.cb4 = false;
  $scope.data.cb5 = false;


});
